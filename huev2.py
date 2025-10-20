#!/usr/local/bin/python3

import urllib3
import udi_interface

LOGGER = udi_interface.LOGGER

class PhueException(Exception):
    def __init__(self, id, message):
        self.id = id
        self.message = message


class PhueRegistrationException(PhueException):
    pass


class PhueRequestTimeout(PhueException):
    pass


class HueBridge:
    """
    Hue Bridge API v2
    """
    def __init__(self, hub_ip, username=None):
        self.hub_ip = hub_ip
        self.username = username
        self.headers = None
        self.bridge_pool = None
        self.bridge_id = None
        self.bridge_conn()

    @staticmethod
    def discover_bridges():
        discovered_bridges = []
        resp = urllib3.request("GET", "https://discovery.meethue.com")
        if resp.status != 200:
            LOGGER.error(f"Error discovering Hue bridges online {resp.status}")
            return None
        for entry in resp.json():
            discovered_bridges.append(entry["internalipaddress"])
        return discovered_bridges

    def bridge_conn(self):
        """ close any prior connections """
        if self.bridge_pool is not None:
            self.bridge_pool.close()
            self.bridge_pool=None

        """ retrieve username if not provided """
        if self.username is None:
            self.bridge_pool = urllib3.HTTPSConnectionPool(self.hub_ip, cert_reqs="CERT_REQUIRED", ca_certs="hue.crt",
                                                           assert_hostname=False)
            auth = self.get_token()
            if auth is not None:
                self.username = auth["username"]
                self.bridge_pool.close()
            else:
                raise PhueRegistrationException(403, 'Link button is not pressed')

        """ establish default connection pool """
        self.headers = {"hue-application-key": self.username}
        self.bridge_pool = urllib3.HTTPSConnectionPool(self.hub_ip, cert_reqs="CERT_REQUIRED", ca_certs="hue.crt",
                                                       assert_hostname=False, headers=self.headers)
        self.get_bridge()

    def get_token(self):
        data = {"devicetype":"polyglot#udi-hue-pg3", "generateclientkey": True}
        headers = {"Content-Type": "application/json"}
        req = self.bridge_pool.request("POST", "/api", headers=headers, json=data)
        if req.status != 200:
            LOGGER.error(f"Error requesting API token: {req.status}")
            return None
        if "error" in req.json()[0]:
            err = req.json()[0]["error"]["description"]
            LOGGER.error(f"Error requesting API token: {err}")
            return None
        if "success" in req.json()[0]:
            result = req.json()[0]["success"]
            LOGGER.debug(f"Got username: {result['username']}")
            return result
        return None

    def get_bridge(self):
        req = self.bridge_pool.request("GET", "/clip/v2/resource/bridge")
        if req.status == 403:
            raise PhueRegistrationException(403, 'Invalid token')
        if req.status != 200:
            LOGGER.error(f"Error requesting bridges: {req.status}")
            return False
        self.bridge_id = req.json()["data"][0]["bridge_id"]
        return req.json()["data"]

    def get_lights(self):
        req = self.bridge_pool.request("GET", "/clip/v2/resource/light")
        if req.status != 200:
            LOGGER.error(f"Error requesting lights: {req.status}")
            return False
        return req.json()["data"]

    def get_groups(self):
        req = self.bridge_pool.request("GET", "/clip/v2/resource/grouped_light")
        if req.status != 200:
            LOGGER.error(f"Error requesting groups: {req.status}")
            return False
        return req.json()["data"]

    def get_rooms(self):
        req = self.bridge_pool.request("GET", "/clip/v2/resource/room")
        if req.status != 200:
            LOGGER.error(f"Error requesting rooms: {req.status}")
            return False
        return req.json()["data"]

    def get_zones(self):
        req = self.bridge_pool.request("GET", "/clip/v2/resource/zone")
        if req.status != 200:
            LOGGER.error(f"Error requesting zones: {req.status}")
            return False
        return req.json()["data"]

    def get_devices(self):
        req = self.bridge_pool.request("GET", "/clip/v2/resource/device")
        if req.status != 200:
            LOGGER.error(f"Error requesting lights: {req.status}")
            return False
        return req.json()["data"]

    def get_motion(self):
        req = self.bridge_pool.request("GET", "/clip/v2/resource/motion")
        if req.status != 200:
            LOGGER.error(f"Error requesting motion sensors: {req.status}")
            return False
        return req.json()["data"]

    def get_grouped_motion(self):
        req = self.bridge_pool.request("GET", "/clip/v2/resource/grouped_motion")
        if req.status != 200:
            LOGGER.error(f"Error requesting motion sensors groups: {req.status}")
            return False
        return req.json()["data"]

    def get_scenes(self):
        req = self.bridge_pool.request("GET", "/clip/v2/resource/scene")
        if req.status != 200:
            LOGGER.error(f"Error requesting scenes: {req.status}")
            return False
        return req.json()["data"]

    def get_zigbee_connectivity(self):
        req = self.bridge_pool.request("GET", "/clip/v2/resource/zigbee_connectivity")
        if req.status != 200:
            LOGGER.error(f"Error getting zigbee connectivity: {req.status}")
            return False
        return req.json()["data"]

    def set_light(self, light_id, command):
        headers = self.headers
        headers["Content-Type"] = "application/json"
        req = self.bridge_pool.request("PUT", f"/clip/v2/resource/light/{light_id}", headers=headers, json=command)
        if req.status != 200:
            LOGGER.error(f"Error setting light: {req.status} {req.data}")
            return False
        return req.json()["data"]

    def set_group(self, group_id, command):
        headers = self.headers
        headers["Content-Type"] = "application/json"
        req = self.bridge_pool.request("PUT", f"/clip/v2/resource/grouped_light/{group_id}", headers=headers, json=command)
        if req.status != 200:
            LOGGER.error(f"Error setting group: {req.status} {req.data}")
            return False
        return req.json()["data"]

    def set_scene(self, scene_id, command):
        headers = self.headers
        headers["Content-Type"] = "application/json"
        req = self.bridge_pool.request("PUT", f"/clip/v2/resource/scene/{scene_id}", headers=headers, json=command)
        if req.status != 200:
            LOGGER.error(f"Error setting scene: {req.status} {req.data}")
            return False
        return req.json()["data"]
