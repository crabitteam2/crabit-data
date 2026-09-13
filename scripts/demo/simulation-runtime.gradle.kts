import org.gradle.api.tasks.JavaExec

// Only the three documented simulation tasks; no application source/task changes.
allprojects {
    tasks.withType<JavaExec>().configureEach {
        if (name in setOf("simulationSession", "simulationRun", "simulationImport")) {
            maxHeapSize = "6g"
            val measuredJava = System.getenv("CRABIT_SIMULATION_MEASURED_JAVA")
            if (measuredJava != null) setExecutable(measuredJava)
        }
    }
}
