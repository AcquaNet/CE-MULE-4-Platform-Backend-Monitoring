package io.opentelemetry.mule4.agent;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import java.util.Collections;
import java.util.Map;

import org.junit.BeforeClass;
import org.junit.Test;

import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanContext;
import io.opentelemetry.context.Context;
import io.opentelemetry.context.propagation.TextMapGetter;
import io.opentelemetry.mule4.agent.transaction.OtelTransaction;

/** Outgoing trace context (TraceContext.headers) and that the receiving side's extraction joins the same trace. */
public class TraceContextTest {

	@BeforeClass
	public static void noExport() {
		// not traces.exporter=none: with it the SDK hands out invalid (all-zero) spans; a dead local port instead
		System.setProperty("otel.exporter.otlp.endpoint", "http://127.0.0.1:9");
		// metrics/logs export: not set here, the agent's DEFAULTS turn them off (see metricsAndLogsOffByDefault)
	}

	@Test
	public void headersCarryTheFlowsRootSpan() {
		Span root = OtelStarter.getTracer().spanBuilder("flow-a").startSpan();
		OtelHandler.transactionStore.storeTransaction("corr-1", new OtelTransaction(root));
		try {
			Map<String, String> h = TraceContext.headers("corr-1");
			SpanContext sc = root.getSpanContext();
			assertEquals("00-" + sc.getTraceId() + "-" + sc.getSpanId() + "-" + sc.getTraceFlags().asHex(), h.get("traceparent"));

			// what the called app does with it (TransactionUtils.extractRemoteContext): its root span joins the trace
			Context remote = OtelStarter.getOpenTelemetry().getPropagators().getTextMapPropagator()
					.extract(Context.root(), h, new TextMapGetter<Map<String, String>>() {
						public Iterable<String> keys(Map<String, String> c) {
							return c.keySet();
						}

						public String get(Map<String, String> c, String key) {
							return c == null ? null : c.get(key);
						}
					});
			Span child = OtelStarter.getTracer().spanBuilder("flow-b").setParent(remote).startSpan();
			assertEquals(sc.getTraceId(), child.getSpanContext().getTraceId());
			child.end();
		} finally {
			OtelHandler.transactionStore.retrieveTransaction("corr-1");
			root.end();
		}
	}

	@Test
	public void httpRequestInProgressIsTheParent() {
		Span root = OtelStarter.getTracer().spanBuilder("flow-a").startSpan();
		OtelTransaction t = new OtelTransaction(root);
		OtelHandler.transactionStore.storeTransaction("corr-2", t);
		Span request = OtelStarter.getTracer().spanBuilder("Request B").setParent(t.getContext()).startSpan();
		try {
			t.setOutgoing(request);  // what SpanUtils.startSpan does for http:request
			assertTrue(TraceContext.headers("corr-2").get("traceparent").contains(request.getSpanContext().getSpanId()));
			t.clearOutgoing(request);  // SpanUtils.endSpan: back to the root span
			assertTrue(TraceContext.headers("corr-2").get("traceparent").contains(root.getSpanContext().getSpanId()));
		} finally {
			OtelHandler.transactionStore.retrieveTransaction("corr-2");
			request.end();
			root.end();
		}
	}

	@Test
	public void metricsAndLogsOffByDefault() {
		OtelStarter.getTracer();
		String meter = OtelStarter.sdk().getSdkMeterProvider().toString();
		String logs = OtelStarter.sdk().getSdkLoggerProvider().toString();
		assertTrue(meter, meter.contains("metricReaders=[]"));
		assertTrue(logs, logs.contains("logRecordProcessor=NoopLogRecordProcessor"));
	}

	@Test
	public void noFlowNoHeaders() {
		assertTrue(TraceContext.headers("no-such-flow").isEmpty());
		assertEquals(Collections.emptyMap(), TraceContext.headers(null));
	}
}
