package io.opentelemetry.mule4.agent;

import java.io.IOException;
import java.io.InputStream;
import java.util.HashMap;
import java.util.Map;
import java.util.Properties;

import org.mule.runtime.api.lifecycle.Disposable;
import org.mule.runtime.api.lifecycle.Initialisable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import io.opentelemetry.api.OpenTelemetry;
import io.opentelemetry.api.common.AttributeKey;
import io.opentelemetry.api.common.Attributes;
import io.opentelemetry.api.common.AttributesBuilder;
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.instrumentation.runtimetelemetry.RuntimeTelemetry;
import io.opentelemetry.sdk.OpenTelemetrySdk;
import io.opentelemetry.sdk.autoconfigure.AutoConfiguredOpenTelemetrySdk;
import io.opentelemetry.sdk.resources.Resource;

/**
 * Initializes the OpenTelemetry SDK for one Mule application (declared as an object in tracer.xml).
 *
 * The agent jar lives in the app's lib, so each app gets its own SDK (statics are per app classloader).
 * serviceName / serviceVersion (tracer.xml: ${app.name}, the app's version) become service.name and
 * service.version, so apps sharing a worker report as separate services; everything else comes from the
 * standard OTEL_* environment (endpoint, protocol, OTEL_RESOURCE_ATTRIBUTES such as worker.id).
 * The SDK is closed on dispose: its exporter threads would otherwise pin the old app's classloader on
 * every redeploy.
 */
public class OtelStarter implements Initialisable, Disposable {

	private static final String INSTRUMENTATION_NAME = "io.opentelemetry.mule4";
	// otel.scope.version of every span: the agent's own Maven version (pom.properties that Maven puts in the jar)
	private static final String INSTRUMENTATION_VERSION = agentVersion();

	private static Logger logger = LoggerFactory.getLogger(OtelStarter.class);

	private static String agentVersion() {
		try (InputStream in = OtelStarter.class.getResourceAsStream(
				"/META-INF/maven/io.opentelemetry.mule4/otel-mule4-agent/pom.properties")) {
			Properties p = new Properties();
			if (in != null) {
				p.load(in);
			}
			return p.getProperty("version", "unknown");
		} catch (IOException e) {
			return "unknown";
		}
	}
	/**
	 * The agent only makes traces (and the platform's intake, Jaeger, only takes traces): metrics and logs export
	 * default to off, else the SDK posts them every minute and logs a 404. OTEL_* env / otel.* system properties win.
	 */
	static final Map<String, String> DEFAULTS = new HashMap<>();
	static {
		DEFAULTS.put("otel.metrics.exporter", "none");
		DEFAULTS.put("otel.logs.exporter", "none");
	}

	private static volatile OpenTelemetrySdk sdk;
	private static volatile AutoCloseable runtimeMetrics;
	private static volatile OpenTelemetry openTelemetry;
	private static volatile Tracer tracer;

	private String serviceName;
	private String serviceVersion;

	public void setServiceName(String serviceName) {
		this.serviceName = serviceName;
	}

	public void setServiceVersion(String serviceVersion) {
		this.serviceVersion = serviceVersion;
	}

	@Override
	public void initialise() {
		initializeOpenTelemetry(serviceName, serviceVersion);
	}

	@Override
	public void dispose() {
		shutdown();
	}

	private static synchronized void initializeOpenTelemetry(String name, String version) {
		if (openTelemetry != null) {
			return;
		}
		try {
			AttributesBuilder attrs = Attributes.builder();
			if (name != null && !name.isEmpty()) {
				attrs.put(AttributeKey.stringKey("service.name"), name);
			}
			if (version != null && !version.isEmpty()) {
				attrs.put(AttributeKey.stringKey("service.version"), version);
			}
			Resource app = Resource.create(attrs.build());
			sdk = AutoConfiguredOpenTelemetrySdk.builder()
					.addPropertiesSupplier(() -> DEFAULTS)
					.addResourceCustomizer((resource, config) -> resource.merge(app))
					.build()
					.getOpenTelemetrySdk();
			openTelemetry = sdk;
			runtimeMetrics = startRuntimeMetrics(sdk);
			logger.info("OpenTelemetry initialized for service {} {}", name, version);
		} catch (Exception e) {
			logger.error("Failed to initialize OpenTelemetry, tracing disabled", e);
			openTelemetry = OpenTelemetry.noop();
		}
		tracer = openTelemetry.getTracer(INSTRUMENTATION_NAME, INSTRUMENTATION_VERSION);
	}

	/**
	 * JVM metrics (jvm.memory.*, jvm.gc.duration, jvm.thread.count, jvm.cpu.*, jvm.class.*) on this SDK's meters: they
	 * only leave the JVM when a metrics exporter is configured (OTEL_METRICS_EXPORTER, default none). Never fatal.
	 */
	static AutoCloseable startRuntimeMetrics(OpenTelemetry otel) {
		try {
			return RuntimeTelemetry.create(otel);
		} catch (Throwable t) {
			logger.warn("JVM metrics not available: {}", t.toString());
			return null;
		}
	}

	private static synchronized void shutdown() {
		if (runtimeMetrics != null) {
			try {
				runtimeMetrics.close();
			} catch (Exception e) {
				// closing observers only
			}
			runtimeMetrics = null;
		}
		if (sdk != null) {
			sdk.close();  // flushes pending spans, stops exporter threads
		}
		sdk = null;
		openTelemetry = null;
		tracer = null;
	}

	/** The SDK, for tests (null when tracing is off). */
	static OpenTelemetrySdk sdk() {
		return sdk;
	}

	public static OpenTelemetry getOpenTelemetry() {
		if (openTelemetry == null) {
			initializeOpenTelemetry(null, null);
		}
		return openTelemetry;
	}

	public static Tracer getTracer() {
		if (tracer == null) {
			initializeOpenTelemetry(null, null);
		}
		return tracer;
	}
}
