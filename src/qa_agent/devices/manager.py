"""DeviceManager: punto único para descubrir y seleccionar dispositivos de cualquier plataforma.

MVP: ejecución secuencial sobre un dispositivo. La interfaz devuelve listas para permitir
ejecución paralela/multi-dispositivo en versiones futuras.
"""
from __future__ import annotations

from qa_agent.core.contracts import Device, DeviceProvider

from .android import AndroidDeviceProvider
from .ios import IOSDeviceProvider


class DeviceManager:
    def __init__(self) -> None:
        self.providers: dict[str, DeviceProvider] = {
            "android": AndroidDeviceProvider(),
            "ios": IOSDeviceProvider(),
        }

    def provider(self, platform: str) -> DeviceProvider:
        return self.providers[platform]

    def list_all(self) -> list[Device]:
        devices: list[Device] = []
        for p in self.providers.values():
            devices.extend(p.list_devices())
        return devices

    def select(self, platform: str, device_id: str | None = None) -> Device:
        prov = self.providers[platform]
        ok, why = prov.is_available()
        if not ok:
            raise RuntimeError(f"Plataforma {platform} no disponible: {why}")
        devices = prov.list_devices()
        if device_id:
            for d in devices:
                if d.id == device_id:
                    if not d.available:
                        raise RuntimeError(f"Dispositivo {device_id} en estado '{d.state}'")
                    return d
            raise RuntimeError(f"Dispositivo {device_id} no encontrado")
        ready = [d for d in devices if d.available]
        if not ready:
            states = ", ".join(f"{d.id}={d.state}" for d in devices) or "ninguno conectado"
            raise RuntimeError(f"No hay dispositivos {platform} disponibles ({states})")
        # Preferir físico sobre emulador: refleja mejor la app real con su cuenta de prueba.
        ready.sort(key=lambda d: 0 if "physical" in d.kind.value else 1)
        return ready[0]
