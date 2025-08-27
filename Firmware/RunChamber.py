# Voxelis AI 2025
# Written by Christopher Pederson
# Thermal chamber raspberry pi controll systems 
# Using PiRelay-V2 Sheild and SEQUENT Microsystems Thermocouple DAQ Shield

import os
import sys
import signal
import csv
import time
from datetime import datetime
from pathlib import Path
import pytz

import PiRelay  # Relay sheild python library
import sm_tc    # Thermocouple sheild python library
from simple_pid import PID  # PID control library

# -------------------------------
# Headless / live-plot gating
# -------------------------------
HEADLESS = (os.environ.get("DISPLAY") in (None, "")) or (not sys.stdout.isatty()) 
# currently not functional i think youll have to look into running an X server because TMUX disables the headless enviroment configuration info... but i aint doin allat 
if HEADLESS:
    import matplotlib
    matplotlib.use("Agg")
import matplotlib.pyplot as plt  # safe: Agg in headless

# -------------------------------
# Setup Vancouver timestamp + CSV (durable)
# -------------------------------
log_dir = Path.home() / "chamber_logs"
log_dir.mkdir(parents=True, exist_ok=True)

vancouver_tz = pytz.timezone("America/Vancouver")
start_time = datetime.now(vancouver_tz)

filename = start_time.strftime("TC_DATA_EVENT:_%H:%M:%S_%Y-%m-%d.csv")
csv_path = log_dir / filename

csv_file = open(csv_path, mode="w", newline="", buffering=1)
csv_writer = csv.writer(csv_file)
csv_writer.writerow([
    "Timestamp (local)", "ChamberTemp", "SetTemp", "ControlOutput",
    "TC1", "TC2", "TC3", "TC4", "TC5", "TC6", "TC7", "TC8"
])

def _durable_row_write(row):
    csv_writer.writerow(row)
    csv_file.flush()
    os.fsync(csv_file.fileno())

# Relay Declerations
rlyBlower = PiRelay.Relay("RELAY3")
rlyHeater = PiRelay.Relay("RELAY4")
rlyDutPwr = PiRelay.Relay("RELAY2")
rlyDutCtrl = PiRelay.Relay("RELAY1")

# Set the heater and blower to off
rlyHeater.off()
rlyBlower.off()
rlyDutPwr.off()
rlyDutCtrl.off()

# Initialize SMtc Object
tc = sm_tc.SMtc(0)
# 0 refers to the stack number, chamber currently only uses one SM board. this value is set on the dip switches

# Control Functions
def shutoff():
    rlyDutPwr.off()
    rlyDutCtrl.off()
    rlyHeater.off()
    rlyBlower.off()

# -------------------------------
# Enforce persistent-only execution (tmux/screen/nohup/systemd)
# -------------------------------

def _is_persistent_context() -> bool:
    # tmux or screen
    if os.environ.get("TMUX") or os.environ.get("STY"):
        return True
    # nohup: SIGHUP ignored or stdout not a TTY
    try:
        if signal.getsignal(signal.SIGHUP) == signal.SIG_IGN:
            return True
    except Exception:
        pass
    if not sys.stdout.isatty():
        return True
    # systemd markers
    if os.environ.get("INVOCATION_ID") or os.environ.get("JOURNAL_STREAM"):
        return True
    return False

if not _is_persistent_context():
    print("Process is not persistant: This program requires that you run using TMUX for data protection purposes")
    print("Please re-run program using TMUX")
    print()
    print("Ending current session...")
    time.sleep(5)
    shutoff()
    sys.exit("Process is not persistant")

# Inintialize Thermocouple Map
# Thermocouple types are defined in the SMtc library
# B = 0, E = 1, J = 2, K = 3, N = 4, R = 5, S = 6, T = 7
# The map allows the user to specify a char value and get the corresponding integer value
# This is used to set the thermocouple type for each channel
tc_type_map = {
    "B": 0,
    "E": 1,
    "J": 2,
    "K": 3,
    "N": 4,
    "R": 5,
    "S": 6,
    "T": 7
}

# Ask user for thermocouple type (default K wich is set within the .get as 3)
print()
print("Propery of Voxelis AI 2025")
print("Thermal Chamber Control System")
print()
tcTypeInput = input("Enter thermocouple type [B, E, J, K, N, R, S, T] (Default is K):")
tcType = tc_type_map.get(tcTypeInput, 3)

# Initialize each individual channel
tc.set_sensor_type(1,tcType)
tc.set_sensor_type(2,tcType)
tc.set_sensor_type(3,tcType)
tc.set_sensor_type(4,tcType)
tc.set_sensor_type(5,tcType)
tc.set_sensor_type(6,tcType)
tc.set_sensor_type(7,tcType)
tc.set_sensor_type(8,tcType)

# Display channel config
print()
print("Thermocouple Config:")
print("tc1: Ambient Sensor      @ " + str(tc.get_temp(1)))
print("tc2: Ambient Sensor      @ " + str(tc.get_temp(2)))
print("tc3: Ambient Sensor(Hot) @ " + str(tc.get_temp(3)))
print("tc4: Heater Sensor       @ " + str(tc.get_temp(4)))
print("tc5: DUT Saftey          @ " + str(tc.get_temp(5)))
print("tc6: DATA 1              @ " + str(tc.get_temp(6)))
print("tc7: DATA 2              @ " + str(tc.get_temp(7)))
print("tc8: DATA 3              @ " + str(tc.get_temp(8)))
print()

# Ask for desired temperature
setTemp = input("Enter chamber desired temperature (C): ")

try:
    setTemp = float(setTemp)
    if setTemp < 30 or setTemp > 100:
        raise ValueError
except (ValueError, TypeError):
    print("Invalid temperature, defaulting to 30C")
    setTemp = 30

# Set DUT Maximum temperature
# The maximum temp acts as a saftey limit for the DUT to avoid damage and must be placed on the most sensitive component
dutMaxTemp = input("Enter maximum temperature for DUT (Device Under Test) (C), Minimum 20C above chamber desired temperature: ")

try:
    dutMaxTemp = float(dutMaxTemp)
    if dutMaxTemp - setTemp < 20:
        raise ValueError
except (ValueError, TypeError):
    print()
    print("Invalid temperature, defaulting to 20C above chamber desired temperature")
    dutMaxTemp = setTemp + 20


# ensure that the user is ready to power the DUT
print()
input("Are you ready to power the DUT? Press Enter to continue...")
print("Powering DUT...")

# Set the relay for the DUT power
rlyDutPwr.on()
rlyDutCtrl.on()

# Starting the chamber
print()
input("Are you ready to begin the test? Press Enter to continue...")
print("CAUTION: Chamber will be very hot!")
print("Starting thermal chamber test...")

time.sleep(5)

# Initialize PID controller
pid = PID(Kp=5.0, Ki=0.1, Kd=1.0, setpoint=setTemp)
pid.output_limits = (0, 5) # max 5 seconds on-time (print uses 'control' value)
loop_interval = 5

# -------------------------------
# Setup live graph (disabled when headless/detached)
# -------------------------------
if not HEADLESS:
    temps, times = [], []
    plt.ion()
    fig, ax = plt.subplots()
    line, = ax.plot([], [], label="Chamber Temp (C)")
    ax.axhline(y=setTemp, color='r', linestyle='--', label="Set Temp")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Temp (C)")
    ax.legend()
    start_secs = time.time()

    def update_plot(current_temp):
        elapsed = time.time() - start_secs
        temps.append(current_temp)
        times.append(elapsed)
        line.set_xdata(times)
        line.set_ydata(temps)
        ax.relim()
        ax.autoscale_view()
        plt.draw()
        plt.pause(0.01)
else:
    def update_plot(_):
        pass

# Main PID control loop
try:
    while True:
        # Read temperatures from thermocouples once per loop
        t1 = tc.get_temp(1); t2 = tc.get_temp(2); t3 = tc.get_temp(3); t4 = tc.get_temp(4)
        t5 = tc.get_temp(5); t6 = tc.get_temp(6); t7 = tc.get_temp(7); t8 = tc.get_temp(8)

        # Weighted chamber temp
        currentTemp = ((2 * t1) + (2 * t2) + t3) / 5
        control = pid(currentTemp)

        # Keep original console output EXACTLY the same
        print(f"Chamber Temp: {currentTemp:.2f} C, Set Temp: {setTemp:.2f} C, "
              f"DATA1: {t6:.2f}C, DATA2: {t7:.2f}C, "
              f"DATA3: {t8:.2f}C, Control Output: {control:.2f}")

        # CSV row (all 8 channels)
        _durable_row_write([
            datetime.now(vancouver_tz).strftime("%H:%M:%S"),
            f"{currentTemp:.2f}",
            f"{setTemp:.2f}",
            f"{control:.2f}",
            f"{t1:.2f}", f"{t2:.2f}", f"{t3:.2f}", f"{t4:.2f}",
            f"{t5:.2f}", f"{t6:.2f}", f"{t7:.2f}", f"{t8:.2f}",
        ])

        # Live plot (no-op when HEADLESS)
        update_plot(currentTemp)

        # Control the heater and blower based on PID output (windowed PWM)
        on_time = control
        if on_time < 0:
            on_time = 0.0
        if on_time > loop_interval:
            on_time = loop_interval
        off_time = loop_interval - on_time

        if on_time > 0:
            rlyHeater.on()
            rlyBlower.on()
            time.sleep(on_time)
            rlyHeater.off()
            rlyBlower.off()
        if off_time > 0:
            time.sleep(off_time)

        # Check for safety limits
        if t5 > dutMaxTemp:
            print("DUT temperature exceeded maximum limit, shutting down...")
            shutoff()
            break
        if t4 > 200:
            print("Heater temperature exceeded maximum limit, shutting down...")
            shutoff()
            break
        if currentTemp > 200:
            print("Chamber temperature exceeded maximum limit, shutting down...")
            shutoff()
            break

# Try block manual override
except KeyboardInterrupt:
    print("\nTest interrupted. Shutting down...")
    shutoff()
finally:
    # Ensure CSV makes it to disk and hardware is safe-off
    try:
        csv_file.flush()
        os.fsync(csv_file.fileno())
        csv_file.close()
    except Exception:
        pass
    try:
        rlyDutPwr.off(); rlyDutCtrl.off(); rlyHeater.off(); rlyBlower.off()
    except Exception:
        pass
    try:
        import RPi.GPIO as GPIO
        GPIO.cleanup()
    except Exception:
        pass