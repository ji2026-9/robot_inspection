"""Read vendor identity endpoints used by the installed DobotStudio client.

Only HTTP GET requests to the three metadata endpoints below are allowed.
No connection/state POST, authentication, mode change or motion command.
"""
import ipaddress
import json
import urllib.request
import time

PATHS = ('/properties/controllerType', '/properties/cabinetType', '/settings/version')


def read_identity(address):
    ipaddress.ip_address(address)
    result = {'address':address, 'source':'控制器 HTTP 只读接口',
              'received_at':time.time(), 'responses':{}, 'errors':{}}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for path in PATHS:
        try:
            request = urllib.request.Request(f'http://{address}:22000{path}', method='GET')
            with opener.open(request, timeout=2) as response:
                payload = response.read(262145)
                if len(payload)>262144:
                    raise ValueError('设备资料响应过大')
            result['responses'][path] = json.loads(payload)
        except Exception as error:
            result['errors'][path] = str(error)
    return result


if __name__ == '__main__':
    print(json.dumps(read_identity('192.168.5.1'),ensure_ascii=False,indent=2))
