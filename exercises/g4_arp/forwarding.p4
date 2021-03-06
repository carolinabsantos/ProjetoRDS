/* -*- P4_16 -*- */
#include <core.p4>
#include <v1model.p4>

const bit<8>  TCP_PROTOCOL = 0x06;
const bit<16> TYPE_IPV4 = 0x800;
const bit<16> TYPE_ARP = 0x806;

const bit<16> ARP_REQUEST = 1;
const bit<16> ARP_REPLY = 2;

/*************************************************************************
*********************** H E A D E R S  ***********************************
*************************************************************************/

typedef bit<9>  egressSpec_t;
typedef bit<48> macAddr_t;
typedef bit<32> ip4Addr_t;

header ethernet_t {
    macAddr_t dstAddr;
    macAddr_t srcAddr;
    bit<16>   etherType;
}

header ipv4_t {
    bit<4>    version;
    bit<4>    ihl;
    bit<6>    diffserv;
    bit<2>    ecn;
    bit<16>   totalLen;
    bit<16>   identification;
    bit<3>    flags;
    bit<13>   fragOffset;
    bit<8>    ttl;
    bit<8>    protocol;
    bit<16>   hdrChecksum;
    ip4Addr_t srcAddr;
    ip4Addr_t dstAddr;
}

header arp_t {
    bit<16> hwType16;
    bit<16> protoType;
    bit<8> hwAddrLen;
    bit<8> protoAddrLen;
    bit<16> opcode;
    bit<48> hwSrcAddr;
    bit<32> protoSrcAddr;
    bit<48> hwDstAddr;
    bit<32> protoDstAddr;
}

struct metadata {
    bool is_multicast;
}

struct headers {
    ethernet_t   ethernet;
    ipv4_t       ipv4;
    arp_t        arp;
}

/*************************************************************************
*********************** P A R S E R  ***********************************
*************************************************************************/

parser MyParser(packet_in packet,
                out headers hdr,
                inout metadata meta,
                inout standard_metadata_t standard_metadata) {

    state start {
        transition parse_ethernet;
    }

    state parse_ethernet {
        packet.extract(hdr.ethernet);
        transition select(hdr.ethernet.etherType) {
            TYPE_IPV4: parse_ipv4;
            TYPE_ARP: parse_arp;
            default: accept;
        }
    }

    state parse_ipv4 {
        packet.extract(hdr.ipv4);
        transition accept;
    }

    state parse_arp {
        packet.extract(hdr.arp);
        transition accept;
    }
}


/*************************************************************************
************   C H E C K S U M    V E R I F I C A T I O N   *************
*************************************************************************/

control MyVerifyChecksum(inout headers hdr, inout metadata meta) {
    apply {  }
}


/*************************************************************************
**************  I N G R E S S   P R O C E S S I N G   *******************
*************************************************************************/

control MyIngress(inout headers hdr,
                  inout metadata meta,
                  inout standard_metadata_t standard_metadata) {
    action drop() {
        mark_to_drop(standard_metadata);
    }

    action ipv4_forward(macAddr_t dstAddr, egressSpec_t port) {
        standard_metadata.egress_spec = port;
        hdr.ethernet.srcAddr = hdr.ethernet.dstAddr;
        hdr.ethernet.dstAddr = dstAddr;
        hdr.ipv4.ttl = hdr.ipv4.ttl - 1;
    }

    table ipv4_lpm {
        key = {
            hdr.ipv4.dstAddr: lpm;
        }
        actions = {
            ipv4_forward;
            NoAction;
        }
        size = 1024;
        default_action = NoAction();
    }


    action start_arp(macAddr_t srcAddr, bit<16> mcast_grp) {
        hdr.arp.setValid();
        hdr.ethernet.etherType = TYPE_ARP;
        hdr.arp.opcode = ARP_REQUEST;
        hdr.arp.hwSrcAddr = srcAddr;
        hdr.arp.protoSrcAddr = hdr.ipv4.srcAddr;
        hdr.arp.protoDstAddr = hdr.ipv4.dstAddr;
        standard_metadata.mcast_grp = mcast_grp;
    }

    table first_arp_packet {
        key = {
            hdr.ipv4.dstAddr: lpm;
        }
        actions = {
            start_arp;
            NoAction;
        }
        size = 1024;
        default_action = NoAction();
    }

    action set_egress_port(egressSpec_t port_num) {
        standard_metadata.egress_spec = port_num;
    }

    table L2_forwarding  {
        key = {
            hdr.ethernet.dstAddr: exact;
        }
        actions = {
            set_egress_port;
            NoAction;
        }
        size = 1024;
        default_action = NoAction();
    }

    action arp_request_to_reply(macAddr_t target_mac) {
        hdr.ethernet.dstAddr = hdr.ethernet.srcAddr;
        hdr.ethernet.srcAddr = target_mac;
        hdr.arp.opcode = ARP_REPLY;
        hdr.arp.hwDstAddr = hdr.arp.hwSrcAddr;
        hdr.arp.hwSrcAddr = target_mac;
        ip4Addr_t dstAddr = hdr.arp.protoSrcAddr;
        hdr.arp.protoSrcAddr = hdr.arp.protoDstAddr;
        hdr.arp.protoDstAddr = dstAddr;
        standard_metadata.egress_spec = standard_metadata.ingress_port;
    }

    table arp_request_reply_table {
        key = {
            hdr.arp.protoDstAddr: lpm;
        }
        actions = {
            arp_request_to_reply;
            NoAction;
        }
        size = 1024;
        default_action = NoAction;
    }


    action set_mcast_grp(bit<16> mcast_grp) {
        standard_metadata.mcast_grp = mcast_grp;
    }

    table forward_request {
        key = {
            hdr.arp.protoDstAddr: lpm;
        }
        actions = {
            set_mcast_grp;
            NoAction;
        }
        size = 1024;
        default_action = NoAction();
    }


    action forward_reply(egressSpec_t port) {
        standard_metadata.egress_spec = port;
    }

    table arp_reply_table {
        key = {
            hdr.arp.protoDstAddr: lpm;
        }
        actions = {
            forward_reply;
            NoAction;
        }
        size = 1024;
        default_action = NoAction();
    }

    apply {
        if (hdr.ipv4.isValid()) {
            if (!ipv4_lpm.apply().hit) {
                first_arp_packet.apply();
            }
        }
        L2_forwarding.apply();
        if (hdr.arp.isValid() && hdr.arp.opcode == ARP_REQUEST) {
            if (arp_request_reply_table.apply().hit) {
                forward_request.apply();
            }
        }
        if (hdr.arp.isValid() && hdr.arp.opcode == ARP_REPLY) {
            arp_reply_table.apply();
        }
    }
}

/*************************************************************************
****************  E G R E S S   P R O C E S S I N G   *******************
*************************************************************************/

control MyEgress(inout headers hdr,
                 inout metadata meta,
                 inout standard_metadata_t standard_metadata) {
    apply {  }
}

/*************************************************************************
*************   C H E C K S U M    C O M P U T A T I O N   **************
*************************************************************************/

control MyComputeChecksum(inout headers hdr, inout metadata meta) {
     apply {
	update_checksum(
	    hdr.ipv4.isValid(),
            { hdr.ipv4.version,
	      hdr.ipv4.ihl,
	      hdr.ipv4.diffserv,
	      hdr.ipv4.ecn,
              hdr.ipv4.totalLen,
              hdr.ipv4.identification,
              hdr.ipv4.flags,
              hdr.ipv4.fragOffset,
              hdr.ipv4.ttl,
              hdr.ipv4.protocol,
              hdr.ipv4.srcAddr,
              hdr.ipv4.dstAddr },
            hdr.ipv4.hdrChecksum,
            HashAlgorithm.csum16);
    }
}

/*************************************************************************
***********************  D E P A R S E R  *******************************
*************************************************************************/

control MyDeparser(packet_out packet, in headers hdr) {
    apply {
        packet.emit(hdr.ethernet);
        packet.emit(hdr.ipv4);
        packet.emit(hdr.arp);
    }
}

/*************************************************************************
***********************  S W I T C H  *******************************
*************************************************************************/

V1Switch(
MyParser(),
MyVerifyChecksum(),
MyIngress(),
MyEgress(),
MyComputeChecksum(),
MyDeparser()
) main;
