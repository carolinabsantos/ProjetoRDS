#!/usr/bin/env python2
import argparse
import grpc
import os
import sys
from time import sleep

# Import P4Runtime lib from parent utils dir
# Probably there's a better way of doing this.
sys.path.append(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 '../../utils/'))
import p4runtime_lib.bmv2
from p4runtime_lib.switch import ShutdownAllSwitchConnections
import p4runtime_lib.helper


def writeForwardingRules(p4info_helper, ingress_sw, port,
                     dst_eth_addr, dst_ip_addr):
    """
    Installs a forwarding rule

    :param p4info_helper: the P4Info helper
    :param ingress_sw: the ingress switch connection
    :param egress_sw: the egress switch connection
    :param port: the port into which the packet will be forwarded
    :param dst_eth_addr: the destination IP to match in the ingress rule
    :param dst_ip_addr: the destination Ethernet address to write in the
                        egress rule
    """
    # 1) Forwarding Rule
    table_entry = p4info_helper.buildTableEntry(
        table_name="MyIngress.ipv4_lpm",
        match_fields={
            "hdr.ipv4.dstAddr": (dst_ip_addr, 32)
        },
        action_name="MyIngress.ipv4_forward",
        action_params={
            "dstAddr"   : dst_eth_addr,
            "port"      : port
        })
    ingress_sw.WriteTableEntry(table_entry)
    print "Installed forwarding rule on %s" % ingress_sw.name



def readTableRules(p4info_helper, sw):
    """
    Reads the table entries from all tables on the switch.

    :param p4info_helper: the P4Info helper
    :param sw: the switch connection
    """
    print '\n----- Reading tables rules for %s -----' % sw.name
    for response in sw.ReadTableEntries():
        for entity in response.entities:
            entry = entity.table_entry
            table_name = p4info_helper.get_tables_name(entry.table_id)
            print '%s: ' % table_name,
            for m in entry.match:
                print p4info_helper.get_match_field_name(table_name, m.field_id),
                print '%r' % (p4info_helper.get_match_field_value(m),),
            action = entry.action.action
            action_name = p4info_helper.get_actions_name(action.action_id)
            print '->', action_name,
            for p in action.params:
                print p4info_helper.get_action_param_name(action_name, p.param_id),
                print '%r' % p.value,
            print


def printGrpcError(e):
    print "gRPC Error:", e.details(),
    status_code = e.code()
    print "(%s)" % status_code.name,
    traceback = sys.exc_info()[2]
    print "[%s:%d]" % (traceback.tb_frame.f_code.co_filename, traceback.tb_lineno)

def main(p4info_file_path, bmv2_file_path):
    # Instantiate a P4Runtime helper from the p4info file
    p4info_helper = p4runtime_lib.helper.P4InfoHelper(p4info_file_path)

    try:
        # Create a switch connection object for s1 and s2;
        # this is backed by a P4Runtime gRPC connection.
        # Also, dump all P4Runtime messages sent to switch to given txt files.
        s1 = p4runtime_lib.bmv2.Bmv2SwitchConnection(
            name='s1',
            address='127.0.0.1:50051',
            device_id=0,
            proto_dump_file='logs/s1-p4runtime-requests.txt')
        s2 = p4runtime_lib.bmv2.Bmv2SwitchConnection(
            name='s2',
            address='127.0.0.1:50052',
            device_id=1,
            proto_dump_file='logs/s2-p4runtime-requests.txt')
        s3 = p4runtime_lib.bmv2.Bmv2SwitchConnection(
            name='s3',
            address='127.0.0.1:50053',
            device_id=2,
            proto_dump_file='logs/s3-p4runtime-requests.txt')

        # Send master arbitration update message to establish this controller as
        # master (required by P4Runtime before performing any other write operation)
        s1.MasterArbitrationUpdate()
        s2.MasterArbitrationUpdate()
        s3.MasterArbitrationUpdate()

        # Install the P4 program on the switches
        s1.SetForwardingPipelineConfig(p4info=p4info_helper.p4info,
                                       bmv2_json_file_path=bmv2_file_path)
        print "Installed P4 Program using SetForwardingPipelineConfig on s1"
        s2.SetForwardingPipelineConfig(p4info=p4info_helper.p4info,
                                       bmv2_json_file_path=bmv2_file_path)
        print "Installed P4 Program using SetForwardingPipelineConfig on s2"
        s3.SetForwardingPipelineConfig(p4info=p4info_helper.p4info,
                                       bmv2_json_file_path=bmv2_file_path)
        print "Installed P4 Program using SetForwardingPipelineConfig on s3"

        # Write the rules that tunnel traffic from h1 to h2
        writeForwardingRules(p4info_helper, ingress_sw=s1, port=1,
                         dst_eth_addr="08:00:00:00:02:02", dst_ip_addr="10.0.2.20")

        # Write the rules that tunnel traffic from h1 to h3
        writeForwardingRules(p4info_helper, ingress_sw=s1, port=2,
                         dst_eth_addr="08:00:00:00:03:03", dst_ip_addr="10.0.3.30")

        # Write the rules that tunnel traffic from h1 to h4
        writeForwardingRules(p4info_helper, ingress_sw=s1, port=2,
                         dst_eth_addr="08:00:00:00:03:44", dst_ip_addr="10.0.3.40")

        # Write the rules that tunnel traffic from h2 to h1
        writeForwardingRules(p4info_helper, ingress_sw=s2, port=1,
                         dst_eth_addr="08:00:00:00:01:01", dst_ip_addr="10.0.1.10")

        # Write the rules that tunnel traffic from h2 to h3
        writeForwardingRules(p4info_helper, ingress_sw=s2, port=2,
                         dst_eth_addr="08:00:00:00:03:03", dst_ip_addr="10.0.3.30")

        # Write the rules that tunnel traffic from h2 to h4
        writeForwardingRules(p4info_helper, ingress_sw=s2, port=2,
                         dst_eth_addr="08:00:00:00:03:44", dst_ip_addr="10.0.3.40")

        # Write the rules that tunnel traffic from h3 and h4  to h1
        writeForwardingRules(p4info_helper, ingress_sw=s3, port=1,
                         dst_eth_addr="08:00:00:00:01:01", dst_ip_addr="10.0.1.10")

        # Write the rules that tunnel traffic from h3 and h4  to h2
        writeForwardingRules(p4info_helper, ingress_sw=s3, port=2,
                         dst_eth_addr="08:00:00:00:02:02", dst_ip_addr="10.0.2.20")

        # Write the rules that tunnel traffic from s3 to h3
        writeForwardingRules(p4info_helper, ingress_sw=s3, port=3,
                         dst_eth_addr="08:00:00:00:03:03", dst_ip_addr="10.0.3.30")
        # Write the rules that tunnel traffic from s3 to h4
        writeForwardingRules(p4info_helper, ingress_sw=s3, port=4,
                         dst_eth_addr="08:00:00:00:03:44", dst_ip_addr="10.0.3.40")
        # Write the rules that tunnel traffic from s1 to h1
        writeForwardingRules(p4info_helper, ingress_sw=s1, port=3,
                         dst_eth_addr="08:00:00:00:01:01", dst_ip_addr="10.0.1.10")
        # Write the rules that tunnel traffic from s2 to h2
        writeForwardingRules(p4info_helper, ingress_sw=s2, port=3,
                         dst_eth_addr="08:00:00:00:02:02", dst_ip_addr="10.0.2.20")


        readTableRules(p4info_helper, s1)
        readTableRules(p4info_helper, s2)
        readTableRules(p4info_helper, s3)

    except KeyboardInterrupt:
        print " Shutting down."
    except grpc.RpcError as e:
        printGrpcError(e)

    ShutdownAllSwitchConnections()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='P4Runtime Controller')
    parser.add_argument('--p4info', help='p4info proto in text format from p4c',
                        type=str, action="store", required=False,
                        default='./build/forwarding.p4.p4info.txt')
    parser.add_argument('--bmv2-json', help='BMv2 JSON file from p4c',
                        type=str, action="store", required=False,
                        default='./build/forwarding.json')
    args = parser.parse_args()

    if not os.path.exists(args.p4info):
        parser.print_help()
        print "\np4info file not found: %s\nHave you run 'make'?" % args.p4info
        parser.exit(1)
    if not os.path.exists(args.bmv2_json):
        parser.print_help()
        print "\nBMv2 JSON file not found: %s\nHave you run 'make'?" % args.bmv2_json
        parser.exit(1)
    main(args.p4info, args.bmv2_json)
