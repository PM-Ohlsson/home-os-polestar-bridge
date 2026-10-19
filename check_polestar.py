"""Optional local compatibility test. Never writes credentials to disk."""
import asyncio
from getpass import getpass
from polestar_api import PolestarApi

async def main():
    email = input("Polestar ID email: ").strip()
    password = getpass("Polestar password (input hidden): ")
    async with PolestarApi(email=email, password=password) as api:
        vehicles = await api.get_vehicles()
        print(f"Vehicles found: {len(vehicles)}")
        if not vehicles:
            return
        battery = await vehicles[0].get_battery()
        if battery is None:
            print("Car was found, but no battery data was returned.")
            return
        print(f"Battery: {battery.charge_level}%")
        print(f"Range: {battery.range_km} km")
        print(f"Charging status: {getattr(battery.charging_status, 'name', 'unknown')}")
        print(f"Charging power: {battery.power_watts / 1000:.1f} kW")

if __name__ == "__main__":
    asyncio.run(main())
