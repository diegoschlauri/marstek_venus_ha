# notes stefan

## 2025-12-16

### PossibleImprovements

- reduce the number of set calls to the batteries
   - e.g. set rs485 force mode only once (or all 10 min)
   - dto. rs485 control mode
   - dto. charge power / dischage power (if not changed)

- handle script already running warning -> pause the coordinator update for n seconds to give the script time to finish

- remove the necessacity of helper aliases by using the switch entities directly (more flexible way to configure entities).

- add and amplification factor 

- add a sensor for pv power and never put load on the battery more than the pv power