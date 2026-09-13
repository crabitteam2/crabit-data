import java.nio.file.*;
import tools.jackson.databind.ObjectMapper;
import com.crabit.backend.recommendation.SimulationFeedRankingVerifier;
class FeedRankingDiagnostic {
 public static void main(String[] args) throws Exception {
  var json=new ObjectMapper();
  var request=json.readTree(Files.readAllBytes(Path.of(args[0])));
  var response=json.readTree(Files.readAllBytes(Path.of(args[1])));
  try { System.out.println(json.writeValueAsString(SimulationFeedRankingVerifier.verify(request,response))); }
  catch(Exception failure) {
   failure.printStackTrace();
   var method=SimulationFeedRankingVerifier.class.getDeclaredMethod("expectedOrder",tools.jackson.databind.JsonNode.class);
   method.setAccessible(true);System.out.println(json.writeValueAsString(method.invoke(null,request)));System.exit(1);
  }
 }
}
