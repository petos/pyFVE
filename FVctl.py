#!/bin/env python3

import argparse
import logging
import requests
import yaml
import time
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger("FVEopt")

@dataclass
class LoadDevice:
    id: int
    jmeno: str
    spotreba: int
    ha_endpoint_teplota_min: str
    ha_endpoint_teplota_max: str
    ha_endpoint_teplota_aktualni: str
    ha_endpoint_dovolena: str = ""
    ha_endpoint_ctrl: str = ""
    teplota_aktualni: float = None
    teplota_max: float = None
    teplota_min: float = None
    stav: bool = False
    stary_stav: bool = None
    dovolena: bool = True
    sunday_boost: int = 5

# Configuration holders
load_devices: List[LoadDevice] = []
low_tariff_entity: str = ""
hass_base_url: str = ""
hass_token: str = ""
hass_current_entity: str = ""
hass_state_cache: Dict[str, str] = {}

def load_main_config(filepath: str):
    global low_tariff_entity, hass_base_url, hass_token, hass_current_entity
    logger.debug(f"Načítám hlavní konfiguraci z {filepath}...")
    with open(filepath, "r") as f:
        config = yaml.safe_load(f)

    if not config:
        raise ValueError("Hlavní konfigurační soubor je prázdný nebo nevalidní YAML.")

    hass_base_url = config.get("hass_base_url")
    hass_token = config.get("hass_token")
    low_tariff_entity = config.get("low_tariff_entity")
    hass_current_entity = config.get("hass_current_entity")

    if not (hass_base_url and hass_token and low_tariff_entity and hass_current_entity):
        raise KeyError("Chybí některé z povinných polí: hass_base_url, hass_token, low_tariff_entity, hass_current_entity")

def load_device_config(filepath: str):
    global load_devices
    logger.debug(f"Načítám konfiguraci zařízení z {filepath}...")
    with open(filepath, "r") as f:
        config = yaml.safe_load(f)

    if not config or "load_devices" not in config:
        raise ValueError("Soubor zařízení neobsahuje klíč 'load_devices' nebo je prázdný.")

    load_devices = []
    for dev_cfg in config["load_devices"]:
        device = LoadDevice(
            id=dev_cfg["id"],
            jmeno=dev_cfg["jmeno"],
            spotreba=dev_cfg["spotreba"],
            sunday_boost=dev_cfg["sunday_boost"],
            ha_endpoint_teplota_min=dev_cfg["ha_endpoint_teplota_min"],
            ha_endpoint_teplota_max=dev_cfg["ha_endpoint_teplota_max"],
            ha_endpoint_teplota_aktualni=dev_cfg["ha_endpoint_teplota_aktualni"],
            ha_endpoint_ctrl=dev_cfg.get("ha_endpoint_ctrl", ""),
            ha_endpoint_dovolena=dev_cfg.get("ha_endpoint_dovolena", "")
        )
        load_devices.append(device)
    logger.debug(f"Načteno {len(load_devices)} zařízení.")

def ha_cache_states() -> bool:
    global hass_state_cache
    url = f"{hass_base_url}/api/states"
    headers = {"Authorization": f"Bearer {hass_token}"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        hass_state_cache = {item["entity_id"]: item["state"] for item in data}
        logger.debug(f"Načteno {len(hass_state_cache)} stavů z Home Assistant.")
        return True
    except Exception as e:
        logger.error(f"Chyba při načítání stavů z HA: {e}")
        hass_state_cache = {}
        return False

def ha_get_state(entity: str) -> str:
    return hass_state_cache.get(entity)

def get_bool_via_haapi(entity: str) -> bool:
    state = ha_get_state(entity)
    return state and state.lower() in ["on", "true", "1"]

def get_float_from_hass(entity: str) -> float:
    state = ha_get_state(entity)
    try:
        return float(state)
    except (TypeError, ValueError):
        logger.error(f"Neplatná hodnota z {entity}: {state}")
        return None

def get_int_from_hass(entity: str) -> int:
    state = ha_get_state(entity)
    try:
        return int(float(state))
    except (TypeError, ValueError):
        logger.error(f"Neplatná hodnota z {entity}: {state}")
        return None

def get_devices_states():
    for device in load_devices:
        device.stary_stav = get_bool_via_haapi(device.ha_endpoint_ctrl)
        device.dovolena = get_bool_via_haapi(device.ha_endpoint_dovolena)
        logger.debug(f"Zarizeni {device.jmeno}, aktualni stav: {device.stary_stav}")
        device.teplota_aktualni = get_float_from_hass(device.ha_endpoint_teplota_aktualni)
        logger.debug(f"Zarizeni {device.jmeno}, aktualni teplota = {device.teplota_aktualni}")
        device.teplota_max = get_float_from_hass(device.ha_endpoint_teplota_max)
        logger.debug(f"Zarizeni {device.jmeno}, teplota max = {device.teplota_max}")
        device.teplota_min = get_float_from_hass(device.ha_endpoint_teplota_min)
        if device.teplota_aktualni is None or device.teplota_max is None:
            logger.warning(f"Nelze získat teploty pro zařízení {device.jmeno}, přeskočeno.")
            device.stav = False
            return False
        if datetime.now().hour < 12:
            device.teplota_min -= 10
            logger.debug(f"Teplota min snizena o 10C, protoze je pred polednem a je sance dohrat pres FVE")
        else:
            if datetime.today().weekday() == 6:
                device.teplota_min += device.sunday_boost
                logger.debug(f"Teplota min zvednuta o {device.sunday_boost} C, protoze je nedele")
        logger.debug(f"{device.jmeno} ({device.stary_stav}): T_akt={device.teplota_aktualni}, T_MAX={device.teplota_max}, T_MIN={device.teplota_min}")
    return True

def decide_low_tarif(current_free_energy: int, low_tariff: bool) -> int:
    logger.debug(f"Nizky tarif je {low_tariff}")
    if not low_tariff:
        return current_free_energy
    else:
        for device in load_devices:
            if device.dovolena == True:
                logger.info(f"Zarizeni {device.jmeno} ma dovolenou. Nastavuji 20C")
                device.teplota_min = 20
                continue
            if device.teplota_aktualni < device.teplota_min:
                logger.info(f"Zapínám zařízení {device.jmeno} ({device.spotreba} W), aktualni teplota je nizsi nez min. teplota ({device.teplota_aktualni} < {device.teplota_min})")
                current_free_energy -= device.spotreba
                device.stav = True
            else:
                logger.debug(f"Zarizeni {device.jmeno} ({device.spotreba} W) se nezapina, aktualni teplota je vyssi nez min. teplota ({device.teplota_aktualni} > {device.teplota_min})")
    return current_free_energy

def decide_distribution(current_free_energy: int, low_tariff: bool):
    logger.debug(f"Rozhodování o rozdělení energie: {current_free_energy} W, nízký tarif: {low_tariff}")
    for device in load_devices:
        if device.dovolena == True:
            logger.info(f"Zarizeni {device.jmeno} ma dovolenou. Vypinam")
            device.stav == False
            continue
        if device.stav == True:
            logger.debug(f"Zarizeni {device.jmeno} jiz zapnute")
            continue
        if device.teplota_aktualni >= device.teplota_max:
            logger.info(
                f"Zařízení {device.jmeno} se nezapíná – dosažena max. teplota "
                f"(aktuální: {device.teplota_aktualni} >= max: {device.teplota_max})"
            )
            device.stav = False
            continue
        if current_free_energy < device.spotreba:
            logger.info(
                f"Zařízení {device.jmeno} se nezapíná – nedostatek energie "
                f"(zbývá {current_free_energy} W, potřeba: {device.spotreba} W)"
            )
            device.stav = False
            continue
        logger.info(
            f"Zapínám zařízení {device.jmeno} ({device.spotreba} W), dostatek energie {current_free_energy}"
        )
        current_free_energy -= device.spotreba
        device.stav = True

def apply_device_states_to_ha():
    logger.debug("Aplikuji stavy zařízení do Home Assistant...")
    for device in load_devices:
        if not device.ha_endpoint_ctrl:
            logger.warning(f"Zařízení {device.jmeno} nemá definovaný ha_endpoint_ctrl, přeskočeno.")
            continue
        desired_state = "on" if device.stav else "off"
        if device.stary_stav == device.stav:
            logger.info(f"Zarizeni {device.jmeno} uz je -{desired_state}-, nemenime tedy stav")
            continue
        if "." not in device.ha_endpoint_ctrl:
            logger.error(f"Špatný formát ha_endpoint_ctrl u zařízení {device.jmeno}: {device.ha_endpoint_ctrl}")
            continue
        domain, entity = device.ha_endpoint_ctrl.split(".", 1)
        url = f"{hass_base_url}/api/services/{domain}/turn_{desired_state}"
        headers = {
            "Authorization": f"Bearer {hass_token}",
            "Content-Type": "application/json",
        }
        payload = {"entity_id": device.ha_endpoint_ctrl}

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=5)
            response.raise_for_status()
            logger.info(f"{device.jmeno} -> {desired_state.upper()} (endpoint: {device.ha_endpoint_ctrl})")
        except Exception as e:
            logger.error(f"Chyba při nastavování stavu pro {device.jmeno} ({device.ha_endpoint_ctrl}): {e}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--current_power", type=int, default=None, help="Promenná vhodná pro testování")
    parser.add_argument("--device-config", type=str, default="/opt/fve/config/devices.yaml", help="Cesta ke konfiguraci zařízení")
    parser.add_argument("--main-config", type=str, default="/opt/fve/config/fveconfig.yaml", help="Cesta k hlavní konfiguraci")
    parser.add_argument("--debug", action="store_true", help="Zapne DEBUG výstup logování")
    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)
        logger.debug("DEBUG mód zapnut")

    load_main_config(args.main_config)
    load_device_config(args.device_config)

    if not ha_cache_states():
        logger.error("Nepodařilo se načíst data z Home Assistant, čekám 10s...")
        return False

    low_tariff = get_bool_via_haapi(low_tariff_entity)

    if args.current_power is not None:
        logger.debug(f"Current value got from CLI")
        current_power = args.current_power
    else:
        current_power = get_int_from_hass(hass_current_entity)

    if not get_devices_states():
        logger.error("Nepodařilo se načíst validni data z Home Assistant, čekám 10s...")
        return

    current_power = decide_low_tarif(current_power, low_tariff)
    decide_distribution(current_power, low_tariff)
    apply_device_states_to_ha()
    logger.debug(f"Done")

if __name__ == "__main__":
    running = True
    try:
        while running:
            main()
            time.sleep(10)
    except KeyboardInterrupt:
        logger.info("Skript ukončen uživatelem.")
        running = False
