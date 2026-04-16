#!/usr/bin/env python3
import platform
import os

def main():
    print("Hello from Jetson!")
    print(f"Platform: {platform.machine()}")
    print(f"Hostname: {platform.node()}")
    print(f"Python: {platform.python_version()}")
    print(f"User: {os.getenv('USER')}")

if __name__ == "__main__":
    main()
