package io.opentelemetry.mule4.agent.transaction;

import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

import io.opentelemetry.api.common.AttributeKey;
import io.opentelemetry.api.common.Attributes;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanContext;
import io.opentelemetry.api.trace.SpanKind;
import io.opentelemetry.api.trace.StatusCode;
import io.opentelemetry.context.Context;
import io.opentelemetry.mule4.agent.OtelStarter;

/**
 * Wrapper class around OpenTelemetry Span to provide transaction-like semantics.
 * This allows retrieval of some setter-only attributes and tracks additional metadata.
 */
public class OtelTransaction {

	private final Span span;
	private String flowName;
	private final Map<String, String> labels = new ConcurrentHashMap<>();
	private boolean hasException = false;
	private final Context context;

	public OtelTransaction(Span span) {
		this.span = span;
		this.context = Context.current().with(span);
	}

	/**
	 * Set the transaction/span name.
	 */
	public OtelTransaction setName(String name) {
		span.updateName(name);
		return this;
	}

	/**
	 * Set the transaction type (stored as attribute).
	 */
	public OtelTransaction setType(String type) {
		span.setAttribute("transaction.type", type);
		return this;
	}

	/**
	 * Add a label/attribute to the span.
	 */
	public OtelTransaction addLabel(String key, String value) {
		labels.put(key, value);
		span.setAttribute(key, value);
		return this;
	}

	/**
	 * Add a numeric label/attribute.
	 */
	public OtelTransaction addLabel(String key, Number value) {
		span.setAttribute(key, value.doubleValue());
		return this;
	}

	/**
	 * Add a boolean label/attribute.
	 */
	public OtelTransaction addLabel(String key, boolean value) {
		span.setAttribute(key, value);
		return this;
	}

	/**
	 * Get a previously set label.
	 */
	public Optional<String> getLabel(String key) {
		return Optional.ofNullable(labels.get(key));
	}

	/**
	 * End the transaction/span.
	 */
	public void end() {
		span.end();
	}

	/**
	 * Get the trace ID.
	 */
	public String getTraceId() {
		return span.getSpanContext().getTraceId();
	}

	/**
	 * Get the span/transaction ID.
	 */
	public String getId() {
		return span.getSpanContext().getSpanId();
	}

	/**
	 * Record an exception on this span.
	 */
	public String captureException(Throwable throwable) {
		span.recordException(throwable);
		span.setStatus(StatusCode.ERROR, throwable.getMessage());
		return getId();
	}

	/**
	 * Check if span is sampled.
	 */
	public boolean isSampled() {
		return span.getSpanContext().isSampled();
	}

	/**
	 * Get the underlying span.
	 */
	public Span getSpan() {
		return span;
	}

	/**
	 * Get the context with this span.
	 */
	public Context getContext() {
		return context;
	}

	/**
	 * Start a child span.
	 */
	public Span startSpan(String type, String subtype, String action) {
		String spanName = type;
		if (subtype != null && !subtype.isEmpty()) {
			spanName = type + "." + subtype;
		}

		return OtelStarter.getTracer()
				.spanBuilder(spanName)
				.setParent(context)
				.setSpanKind(SpanKind.INTERNAL)
				.setAttribute("span.type", type)
				.setAttribute("span.subtype", subtype != null ? subtype : "")
				.setAttribute("span.action", action != null ? action : "")
				.startSpan();
	}

	/**
	 * Get the flow name.
	 */
	public String getFlowName() {
		return flowName;
	}

	/**
	 * Set the flow name.
	 */
	public void setFlowName(String flowName) {
		this.flowName = flowName;
		span.setAttribute("mule.flow.name", flowName);
	}

	/**
	 * Check if this transaction has an exception.
	 */
	public boolean hasException() {
		return this.hasException;
	}

	/**
	 * Mark that this transaction has an exception.
	 */
	public void setException() {
		this.hasException = true;
	}

	/**
	 * Set result/status.
	 */
	public OtelTransaction setResult(String result) {
		span.setAttribute("transaction.result", result);
		return this;
	}
}
