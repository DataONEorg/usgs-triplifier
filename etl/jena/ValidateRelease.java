import java.util.HashMap;
import java.util.Map;
import java.util.TreeMap;

import org.apache.jena.graph.Graph;
import org.apache.jena.graph.Node;
import org.apache.jena.query.Dataset;
import org.apache.jena.riot.RDFParser;
import org.apache.jena.shacl.ShaclValidator;
import org.apache.jena.shacl.Shapes;
import org.apache.jena.shacl.ValidationReport;
import org.apache.jena.shacl.validation.ReportEntry;
import org.apache.jena.sparql.graph.GraphFactory;
import org.apache.jena.system.Txn;
import org.apache.jena.tdb2.TDB2Factory;

/**
 * Validates the default graph of a TDB2 store against SHACL shapes.
 *
 * One tab-separated line is printed per severity, result path and constraint
 * component, with the number of results, one focus node and its message. The
 * exit status is 0 when validation ran, whatever the results, and 2 for
 * wrong arguments.
 */
public class ValidateRelease {

    public static void main(String[] args) {
        if (args.length != 3) {
            System.err.println("Usage: ValidateRelease <TDB2 store> <shapes Turtle file> <base IRI>");
            System.exit(2);
        }
        String store = args[0];
        String shapesFile = args[1];
        String base = args[2];

        // Relative IRIs in the shapes file are resolved against the base IRI
        Graph shapesGraph = GraphFactory.createDefaultGraph();
        RDFParser.source(shapesFile).base(base).parse(shapesGraph);
        Shapes shapes = Shapes.parse(shapesGraph);

        Dataset dataset = TDB2Factory.connectDataset(store);
        ValidationReport report = Txn.calculateRead(dataset,
            () -> ShaclValidator.get().validate(shapes, dataset.asDatasetGraph().getDefaultGraph()));

        Map<String, Long> counts = new TreeMap<>();
        Map<String, String> examples = new HashMap<>();
        for (ReportEntry entry : report.getEntries()) {
            String key = String.join("\t",
                entry.severity().level().getLocalName(),
                entry.resultPath() == null ? "-" : entry.resultPath().toString(),
                localName(entry.sourceConstraintComponent()));
            counts.merge(key, 1L, Long::sum);
            examples.putIfAbsent(key, entry.focusNode() + "\t" + entry.message().replaceAll("\\s+", " "));
        }
        for (Map.Entry<String, Long> count : counts.entrySet()) {
            String[] parts = count.getKey().split("\t", 2);
            System.out.println(parts[0] + "\t" + count.getValue() + "\t" + parts[1] + "\t" + examples.get(count.getKey()));
        }
    }

    /**
     * Returns the local name of a constraint component IRI.
     *
     * @param component The component, or null.
     * @return The local name, or "-" when there is no component.
     */
    private static String localName(Node component) {
        return component == null ? "-" : component.getLocalName();
    }
}
