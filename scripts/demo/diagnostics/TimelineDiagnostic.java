import java.nio.file.*;
import java.util.*;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.JsonNode;
import com.crabit.backend.simulation.SimulationEventTimeline;
class TimelineDiagnostic {
 public static void main(String[] args) throws Exception {
  var json=new ObjectMapper();var events=new ArrayList<JsonNode>();
  for(var line:Files.readAllLines(Path.of(args[0])))if(!line.isBlank())events.add(json.readTree(line));
  var people=json.readTree(Files.readAllBytes(Path.of(args[1])));var root=Path.of(args[2]);var paths=new HashSet<String>();
  try(var files=Files.walk(root)) {files.filter(Files::isRegularFile).forEach(p->paths.add(root.relativize(p).toString()));}
  System.out.println(new SimulationEventTimeline().verify(events,people,paths));
 }
}
