package io.opentelemetry.mule4.agent;

import java.util.HashMap;
import java.util.Map;
import java.util.Optional;

import io.opentelemetry.mule4.agent.transaction.OtelTransaction;

/**
 * W3C trace context (traceparent, tracestate) of a running flow, for outgoing calls, so the called app's
 * flow joins this trace (it reads traceparent, see TransactionUtils.startTransaction). From DataWeave:
 * <pre>
 * &lt;http:request ...&gt;
 *   &lt;http:headers&gt;#[java!io::opentelemetry::mule4::agent::TraceContext::headers(correlationId)]&lt;/http:headers&gt;
 * </pre>
 * Notification listeners can't change a request, so the app passes the headers itself.
 */
public final class TraceContext {

	private TraceContext() {
	}

	/**
	 * traceparent/tracestate of the flow with this correlation ID: its http:request span in progress (so the called
	 * flow nests inside the call's time), else its root span; empty when there is none (no transaction, tracing off),
	 * so the request simply goes without them.
	 */
	// ponytail: one outgoing span per flow; parallel requests (scatter-gather) may nest under a sibling request
	public static Map<String, String> headers(String correlationId) {
		Map<String, String> headers = new HashMap<>();
		Optional<OtelTransaction> transaction = OtelHandler.getTransaction(correlationId);
		if (transaction.isPresent()) {
			OtelStarter.getOpenTelemetry().getPropagators().getTextMapPropagator()
					.inject(transaction.get().getOutgoingContext(), headers, (carrier, key, value) -> carrier.put(key, value));
		}
		return headers;
	}
}
