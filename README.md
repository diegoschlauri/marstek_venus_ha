# Home Assistant - Intelligente Batteriesteuerung für Marstek Venus E (und andere)

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)

Dies ist eine benutzerdefinierte Home Assistant-Integration zur intelligenten Steuerung von bis zu drei separaten Batteriespeichern. Sie wurde ursprünglich für Marstek Venus E-Systeme konzipiert, kann aber mit **jedem Batteriesystem** verwendet werden, das über entsprechende Entitäten in Home Assistant gesteuert werden kann.

Die Integration steuert die Batterien nicht alle gleichzeitig, sondern aktiviert sie in Leistungsstufen, um die Effizienz zu maximieren und den Eigenverbrauch zu optimieren. Sie beinhaltet eine dynamische Priorisierung der Batterien basierend auf ihrem Ladezustand (SoC) und eine spezielle Logik für die Interaktion mit einer Wallbox.

## Hauptfunktionen

* **Leistungsstufenschaltung**: Nutzt je nach Energiebedarf oder -überschuss eine, zwei oder drei Batterien.
* **Dynamische Priorisierung**: Priorisiert Batterien intelligent. Beim Laden wird die leerste Batterie bevorzugt, beim Entladen die vollste.
* **Glättung der Netzleistung**: Verhindert hektisches Schalten durch Ermittlung der durchschnittlichen Netzleistung über einen konfigurierbaren Zeitraum.
* **Wallbox-Integration**: Intelligente Pausierung des Batterieladens bei hohem PV-Überschuss, um dem Elektroauto Vorrang zu geben, und Schutz vor gleichzeitigem Entladen.
* **Konfigurierbare Grenzen**: Setzen Sie obere und untere SoC-Grenzen, um die Lebensdauer Ihrer Batterien zu schützen.
* **Einfache Konfiguration**: Vollständig über den Home Assistant UI-Konfigurationsflow einrichtbar.

---

## !! Wichtige Voraussetzung !!

Diese Integration steuert die Batterien nicht direkt über eine herstellerspezifische API. Stattdessen **müssen Sie für jede Batterie bereits Entitäten in Home Assistant haben**, um:
1.  Den **Ladezustand (SoC)** zu lesen (z. B. `sensor.batterie_1_soc`).
2.  Die **Ladeleistung** zu steuern (z. B. `number.batterie_1_ladeleistung_setzen`).
3.  Die **Entladeleistung** zu steuern (z. B. `number.batterie_1_entladeleistung_setzen`).

Im Konfigurationsprozess geben Sie den **Basis-Entitätsnamen** für jede Batterie an (z. B. `batterie_1`). Die Integration leitet daraus die Namen der benötigten Entitäten ab, indem sie Suffixe wie `_soc`, `_charge_power` und `_discharge_power` erwartet.

**Beispiel:**
Wenn Sie als Entität für die erste Batterie `marstek_venus_e_x` angeben, muss die Integration folgende Entitäten finden können:
* `sensor.marstek_venus_e_x_soc`
* `number.marstek_venus_e_x_charge_power`
* `number.marstek_venus_e_x_discharge_power`

Stellen Sie sicher, dass diese Entitäten vorhanden und funktionsfähig sind, bevor Sie die Integration einrichten.

---

## Installation

### Über HACS (Empfohlen)

1.  Fügen Sie dieses GitHub-Repository als "Benutzerdefiniertes Repository" in HACS hinzu.
2.  Suchen Sie nach "Intelligente Batteriesteuerung" und installieren Sie die Integration.
3.  Starten Sie Home Assistant neu.

### Manuelle Installation

1.  Laden Sie den Ordner `custom_components/marstek_intelligent_battery` aus diesem Repository herunter.
2.  Kopieren Sie ihn in das `custom_components`-Verzeichnis Ihrer Home Assistant-Installation.
3.  Starten Sie Home Assistant neu.

---

## Konfiguration

Nach der Installation können Sie die Integration über die Home Assistant UI hinzufügen:

1.  Gehen Sie zu **Einstellungen > Geräte & Dienste**.
2.  Klicken Sie auf **Integration hinzufügen** und suchen Sie nach "Marstek Intelligente Batteriesteuerung".
3.  Folgen Sie dem Konfigurationsdialog und geben Sie die erforderlichen Informationen ein.

### Konfigurationsparameter

| Parameter | Beschreibung | Beispiel |
| --- | --- | --- |
| **ID des Netzanschluss-Leistungssensors** | Die Sensor-ID, die den aktuellen Netzbezug (positiver Wert) oder die Netzeinspeisung (negativer Wert) in Watt misst. | `sensor.power_meter_power` |
| **Leistungsglättung in Sekunden** | Zeitfenster in Sekunden, über das der Durchschnitt der Netzleistung gebildet wird, um schnelles Schalten zu vermeiden. | `30` |
| **Entität der ersten Batterie** | Der Basisname der Entitäten für die erste Batterie. | `marstek_batterie_1` |
| **Entität der zweiten Batterie (Optional)** | Der Basisname für die zweite Batterie. Freilassen, wenn nicht vorhanden. | `marstek_batterie_2` |
| **Entität der dritten Batterie (Optional)** | Der Basisname für die dritte Batterie. Freilassen, wenn nicht vorhanden. | `marstek_batterie_3` |
| **Untere Entladegrenze der Batterien (%)** | Die Batterien werden nicht mehr entladen, wenn ihr SoC diesen Wert erreicht. | `10` |
| **Obere Ladegrenze der Batterien (%)** | Die Batterien werden nicht mehr geladen, wenn ihr SoC diesen Wert erreicht. | `95` |
| **Erste Leistungsstufe (W)** | Netzbezug/-einspeisung, ab dem eine zweite Batterie zugeschaltet wird. | `2000` |
| **Zweite Leistungsstufe (W)** | Netzbezug/-einspeisung, ab dem eine dritte Batterie zugeschaltet wird. | `4000` |
| **Zeitintervall der Prioritätsermittlung (Minuten)** | Intervall, in dem die Priorität der Batterien neu bewertet wird (zusätzlich zur Neubewertung bei Lastrichtungswechsel). | `15` |
| **ID des Leistungssensors der Wallbox** | Der Sensor, der die Ladeleistung der Wallbox misst. | `sensor.wallbox_power` |
| **Wallbox maximaler Überschuss (W)** | Beträgt der PV-Überschuss mehr als diesen Wert, wird das Laden der Batterien pausiert, um dem Auto Vorrang zu geben. | `1500` |
| **Wallbox-Sensor für eingestecktes Kabel** | Ein Binärsensor (`on`/`off`), der anzeigt, ob ein Ladekabel am Auto angeschlossen ist. | `binary_sensor.wallbox_cable_plugged_in` |

---

## Funktionsweise im Detail

### Prioritätsermittlung

* **Beim Entladen (Netzbezug)**: Die Batterie mit dem **höchsten** SoC hat die höchste Priorität.
* **Beim Laden (Netzeinspeisung)**: Die Batterie mit dem **niedrigsten** SoC hat die höchste Priorität.
* Eine Batterie wird von der Prioritätenliste entfernt, wenn sie ihre obere/untere SoC-Grenze erreicht.
* Die Priorität wird bei jedem Wechsel zwischen Laden und Entladen sowie alle X Minuten neu bestimmt.

### Leistungssteuerung

Die absolute Netzleistung (`abs(power)`) bestimmt die Anzahl der aktiven Batterien:
1.  **`Leistung <= Stufe 1`**: Nur die Batterie mit der höchsten Priorität wird verwendet.
2.  **`Stufe 1 < Leistung <= Stufe 2`**: Die Leistung wird gleichmäßig auf die zwei Batterien mit der höchsten Priorität aufgeteilt.
3.  **`Leistung > Stufe 2`**: Die Leistung wird gleichmäßig auf alle verfügbaren Batterien aufgeteilt.

Die Logik passt sich automatisch an, wenn aufgrund von SoC-Grenzen weniger Batterien zur Verfügung stehen.

### Wallbox-Logik

Diese Logik ist nur aktiv, wenn das Ladekabel angeschlossen ist:
* **Entladeschutz**: Sobald die Wallbox Strom zieht (`Leistung > 0`), wird das Entladen **aller** Batterien sofort gestoppt, um zu verhindern, dass die Batterie das Auto lädt.
* **Ladevorrang für das Auto**: Wenn der PV-Überschuss (Netzeinspeisung) den konfigurierten Wert (z.B. 1500 W) übersteigt, wird das Laden der Heimbatterien pausiert. Das System geht davon aus, dass dieser hohe Überschuss für das Auto genutzt werden soll.
* **Sicherheits-Timeout**: Wenn das Laden der Batterien wegen hohem Überschuss pausiert wurde, aber das Auto innerhalb von 5 Minuten nicht mit dem Laden beginnt, wird das Laden der Heimbatterien wieder aktiviert, um die Energie nicht ungenutzt ins Netz einzuspeisen.

Viel Erfolg und Freude mit dieser intelligenten Steuerung!
