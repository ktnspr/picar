"""
motortest.py – Misst zwei Eigenschaften der Hinterrad-Motoren für differential.py:

  1. Welcher Motor treibt das linke Rad an?
  2. Ab welchem PWM-Wert dreht sich ein Rad (MINDEST_PWM)?

WICHTIG: Das Auto muss aufgebockt sein (Räder frei in der Luft)!
Der Fernsteuerungs-Server darf nicht gleichzeitig laufen.

Start:   python3 motortest.py
"""

import time

import auto  # noqa: F401 – nur damit picarx nicht nach dem sudo-Passwort fragt
from picarx import Picarx

MOTOR = 0  # dieser Motor wird getestet (Teil 2 und 3)


def motor_drehen(px, motor, pwm):
    """Lässt einen einzelnen Motor mit einem bestimmten PWM-Wert vorwärts drehen."""
    # Vorwärts: linker Motor (0) mit Richtungs-Pin „low“, rechter (1) mit „high“
    if motor == 0:
        px.motor_direction_pins[motor].low()
    else:
        px.motor_direction_pins[motor].high()
    px.motor_speed_pins[motor].pulse_width_percent(pwm)


def main():
    px = Picarx()
    px.stop()
    try:
        input("\nIst das Auto aufgebockt? Dann Enter drücken ...")

        print("\n=== Teil 1: Welcher Motor ist links? ===")
        print("Motor 0 dreht jetzt 2 Sekunden lang.")
        motor_drehen(px, 0, 65)
        time.sleep(2)
        px.stop()
        input("Notiere: Welches Rad hat sich gedreht (links/rechts), und vorwärts oder rückwärts? Enter ...")

        print(f"\n=== Teil 2: Wann bleibt das Rad stehen? (Motor {MOTOR}) ===")
        print("Das Rad dreht und wird bei jedem Enter etwas langsamer.")
        for pwm in range(70, 0, -5):
            motor_drehen(px, MOTOR, pwm)
            input(f"  PWM {pwm:2} %  – dreht das Rad noch? Enter für den nächsten Schritt ...")
        px.stop()

        print(f"\n=== Teil 3: Wann läuft das Rad aus dem Stand an? (Motor {MOTOR}) ===")
        for pwm in range(10, 75, 5):
            px.stop()
            time.sleep(0.5)
            motor_drehen(px, MOTOR, pwm)
            input(f"  PWM {pwm:2} %  – läuft das Rad an? Enter für den nächsten Schritt ...")
        print("\nFertig! Bitte die Ergebnisse von Teil 1, 2 und 3 notieren.")
    finally:
        # Egal was passiert (auch bei Strg+C): Motoren aus
        px.stop()


if __name__ == "__main__":
    main()
