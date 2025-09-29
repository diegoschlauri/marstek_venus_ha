# Home Assistant - Intelligente Batteriesteuerung für Marstek Venus E

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)

Dies ist eine benutzerdefinierte Home Assistant-Integration zur intelligenten Steuerung von bis zu drei separaten Batteriespeichern. Sie wurde ursprünglich für Marstek Venus E-Systeme konzipiert, kann aber mit **jedem Batteriesystem** verwendet werden, das über entsprechende Entitäten in Home Assistant gesteuert werden kann.

Die Integration steuert die Batterien nicht alle gleichzeitig, sondern aktiviert sie in Leistungsstufen, um die Effizienz zu maximieren und den Eigenverbrauch zu optimieren. Sie beinhaltet eine dynamische Priorisierung der Batterien basierend auf ihrem Ladezustand (SoC) und eine erweiterte, optionale Logik für die Interaktion mit einer Wallbox.

## Hauptfunktionen

* **Flexible Anzahl an Batterien**: Steuern Sie eine, zwei oder drei Batterien.
* **Leistungsstufenschaltung**: Nutzt je nach Energiebedarf oder -überschuss eine, zwei oder drei Batterien.
* **Dynamische Priorisierung**: Priorisiert Batterien intelligent. Beim Laden wird die leerste Batterie bevorzugt, beim Entladen die vollste.
* **Glättung der Netzleistung**: Verhindert hektisches Schalten durch Ermittlung der durchschnittlichen Netzleistung über einen konfigurierbaren Zeitraum.
* **Optionale Wallbox-Integration**: Intelligente Pausierung des Batterieladens bei hohem PV-Überschuss. Das Laden wird wiederaufgenommen, wenn das Auto vollgeladen ist oder mit maximaler Leistung lädt, um keine Energie zu verschwenden.
* **Konfigurierbare Grenzen**: Setzen Sie obere und untere SoC-Grenzen, um die Lebensdauer Ihrer Batterien zu schützen.
* **Minimale Lade- und Entladeleistung**: Via Parameter steuerbar ab welchem Überschuss die Batterien zu laden und entladen beginnen um die Effizienz zu steigern.
* **Einfache Konfiguration**: Vollständig über den Home Assistant UI-Konfigurationsflow einrichtbar.

---

## !! Wichtige Voraussetzung !!

Diese Integration steuert die Batterien nicht direkt über eine herstellerspezifische API. Stattdessen **müssen Sie für jede Batterie bereits Entitäten in Home Assistant haben**, um:
1.  Den **Ladezustand (SoC)** zu lesen (z.B. `sensor.batterie_1_soc`).
2.  Die **aktuelle Lade-/Entladeleistung** zu lesen (z.B. `sensor.batterie_1_power`). Ein positiver Wert bedeutet Laden, ein negativer Entladen.
3.  Die **Ladeleistung** zu steuern (z.B. `number.batterie_1_charge_power`).
4.  Die **Entladeleistung** zu steuern (z.B. `number.batterie_1_discharge_power`).

Im Konfigurationsprozess geben Sie den **Basis-Entitätsnamen** für jede Batterie an (z.B. `batterie_1`). Die Integration leitet daraus die Namen der benötigten Entitäten ab, indem sie die Suffixe `_soc`, `_power`, `_charge_power` und `_discharge_power` erwartet.

**Beispiel:**
Wenn Sie als Entität für die erste Batterie `marstek_venus_e_x` angeben, muss die Integration folgende Entitäten finden können:
* `sensor.marstek_venus_e_x_soc`
* `sensor.marstek_venus_e_x_power` **(Wichtig für die Wallbox-Logik)**
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
3.  Folgen Sie dem Konfigurationsdialog. Felder für die Wallbox oder für die Batterien 2 und 3 können freigelassen werden, um die entsprechende Funktionalität zu deaktivieren.

### Konfigurationsparameter

| Parameter | Beschreibung | Beispiel |
| --- | --- | --- |
| **ID des Netzanschluss-Leistungssensors** | Die Sensor-ID, die den aktuellen Netzbezug (+) oder die Einspeisung (-) in Watt misst. | `sensor.power_meter_power` |
| **Leistungsglättung in Sekunden** | Zeitfenster in Sekunden, über das der Durchschnitt der Netzleistung gebildet wird. | `30` |
| **Minimaler Überschuss** | Minimaler Leistungsüberschuss in Watt damit die Ladung staret. | `200` |
| **Minimaler Bezug** | Minimaler Verbrauch in Watt damit die Entladung staret. | `200` |
| **Entität der ersten Batterie** | Der Basisname der Entitäten für die erste Batterie. | `marstek_batterie_1` |
| **Entität der zweiten Batterie (Optional)** | Der Basisname für die zweite Batterie. Freilassen, wenn nicht vorhanden. | `marstek_batterie_2` |
| **Entität der dritten Batterie (Optional)** | Der Basisname für die dritte Batterie. Freilassen, wenn nicht vorhanden. | |
| **Untere Entladegrenze der Batterien (%)** | Die Batterien werden nicht mehr entladen, wenn ihr SoC diesen Wert erreicht. | `10` |
| **Obere Ladegrenze der Batterien (%)** | Die Batterien werden nicht mehr geladen, wenn ihr SoC diesen Wert erreicht. | `95` |
| **Erste Entlade-Leistungsstufe (W)** | Netzbezug, ab dem eine zweite Batterie zugeschaltet wird. | `600` |
| **Zweite Entlade-Leistungsstufe (W)** | Netzbezug, ab dem eine dritte Batterie zugeschaltet wird. | `1200` |
| **Erste Lade-Leistungsstufe (W)** | Netzeinspeisung, ab dem eine zweite Batterie zugeschaltet wird. | `2000` |
| **Zweite Lade-Leistungsstufe (W)** | Netzeinspeisung, ab dem eine dritte Batterie zugeschaltet wird. | `4000` |
| **Zeitintervall der Prioritätsermittlung (Minuten)** | Intervall, in dem die Priorität der Batterien neu bewertet wird. | `15` |
| **ID des Leistungssensors der Wallbox (Optional)**| Der Sensor, der die Ladeleistung der Wallbox misst. | `sensor.wallbox_power` |
| **Wallbox maximaler Überschuss (W) (Optional)**| Beträgt der PV-Überschuss mehr als diesen Wert, wird das Laden der Batterien pausiert. | `1500` |
| **Wallbox-Sensor für eingestecktes Kabel (Optional)**| Ein Binärsensor (`on`/`off`), der anzeigt, ob ein Ladekabel angeschlossen ist. | `binary_sensor.wallbox_cable_plugged_in` |
| **Wallbox Leistungsschwankung(W) für Batterieladefreigabe (Optional)**| Spatzung für Leistungsschwankungen der Wallbox. Sobald die Leistung in den letzten X Sekunden nicht über diesen Wert zugenommen hat, wird das Laden der Batterien wieder ermöglicht. | `200` |
| **Wallbox Aktualisierungs-Zeit für Batterieladefreigabe in Sekunden (Optional)**| Anzahl Minuten bis die Batterien wieder fürs Laden freigebgen werden wenn der Leistungsschwankungswert nicht übertroffen wird. | `300` |

---

## Funktionsweise im Detail

### Prioritätsermittlung

* **Beim Entladen (Netzbezug)**: Die Batterie mit dem **höchsten** SoC hat die höchste Priorität.
* **Beim Laden (Netzeinspeisung)**: Die Batterie mit dem **niedrigsten** SoC hat die höchste Priorität.
* Eine Batterie wird von der Prioritätenliste entfernt, wenn sie ihre obere/untere SoC-Grenze erreicht.

### Leistungssteuerung

Die absolute Netzleistung (`abs(power)`) bestimmt die Anzahl der aktiven Batterien:
1.  **`Leistung <= Stufe 1`**: Nur die Batterie mit der höchsten Priorität wird verwendet.
2.  **`Stufe 1 < Leistung <= Stufe 2`**: Die Leistung wird gleichmäßig auf die zwei Batterien mit der höchsten Priorität aufgeteilt.
3.  **`Leistung > Stufe 2`**: Die Leistung wird gleichmäßig auf alle verfügbaren Batterien aufgeteilt.

### Wallbox-Logik (Nur aktiv, wenn alle Wallbox-Parameter konfiguriert sind)

* **Entladeschutz**: Sobald die Wallbox Strom zieht (`Leistung > 10W`), wird das Entladen **aller** Batterien sofort gestoppt.
* **Ladevorrang für das Auto**: Wenn der **reale PV-Überschuss** (Netzeinspeisung + aktuelle Batterieladeleistung) den konfigurierten Schwellenwert übersteigt, wird das Laden der Heimbatterien pausiert, um dem Auto Vorrang zu geben.
* **Intelligente Lade-Wiederaufnahme**: Das Laden der Batterien wird wieder freigegeben, wenn die Ladeleistung der Wallbox für X-Sekunden stagniert (z.B. weil das Auto voll ist oder seine maximale Ladeleistung erreicht hat). Das Entladen bleibt aber weiterhin gesperrt, solange die Wallbox am Laden ist.
