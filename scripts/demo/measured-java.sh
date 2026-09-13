#!/bin/sh
set -eu
: "${CRABIT_SIMULATION_REAL_JAVA:?actual Java executable required}"
: "${CRABIT_SIMULATION_JVM_METRICS:?metrics output required}"
case " $* " in
  *com.crabit.backend.simulation.Simulation*)
    exec /usr/bin/time -l -o "$CRABIT_SIMULATION_JVM_METRICS" "$CRABIT_SIMULATION_REAL_JAVA" "$@"
    ;;
  *) exec "$CRABIT_SIMULATION_REAL_JAVA" "$@" ;;
esac
