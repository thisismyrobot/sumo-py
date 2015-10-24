""" Simple test client of the XMLRPC server.
"""
import socket
import xmlrpclib

socket.setdefaulttimeout(0.1)

client = xmlrpclib.ServerProxy('http://127.0.0.1:8000')

client.move(20, 0, 0.2)

with open('xmlrpcsumo_testclient.jpg', 'wb') as f:
    f.write(client.pic().data)
