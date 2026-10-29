package io.opentelemetry.mule4.agent.span;

import java.util.Optional;

import javax.xml.namespace.QName;

import org.mule.runtime.api.component.Component;
import org.mule.runtime.api.component.location.ComponentLocation;
import org.mule.runtime.api.notification.MessageProcessorNotification;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanKind;
import io.opentelemetry.api.trace.StatusCode;
import io.opentelemetry.context.Context;
import io.opentelemetry.mule4.agent.OtelStarter;
import io.opentelemetry.mule4.agent.tracing.HttpTracingUtils;
import io.opentelemetry.mule4.agent.transaction.OtelTransaction;
import io.opentelemetry.mule4.agent.transaction.TransactionStore;

/**
 * Creation and ending of OpenTelemetry Spans for Mule message processors.
 */
public class SpanUtils {

	private static final String SUBTYPE = "mule-step";
	private static final String DOC_NAME = "name";
	private static final String DOC_NAMESPACE = "http://www.mulesoft.org/schema/mule/documentation";
	private static final String UNNAMED = "...";
	private static final String UNTYPED = "zzz_type";

	private static final Logger logger = LoggerFactory.getLogger(SpanUtils.class);

	/**
	 * Start a span for a message processor.
	 */
	public static void startSpan(TransactionStore transactionStore, MessageProcessorNotification notification) {
		String transactionId = getTransactionId(notification);

		// Get the parent transaction
		Optional<OtelTransaction> transactionOpt = transactionStore.getTransaction(transactionId);
		if (!transactionOpt.isPresent()) {
			logger.debug("Could not find transaction {}. Skipping span creation.", transactionId);
			return;
		}

		OtelTransaction transaction = transactionOpt.get();

		// Create child span
		Span span = OtelStarter.getTracer()
				.spanBuilder(getStepName(notification))
				.setParent(transaction.getContext())
				.setSpanKind(SpanKind.INTERNAL)
				.setAttribute("mule.processor.type", getSpanType(notification))
				.setAttribute("mule.processor.subtype", getSubType(notification))
				.setAttribute("mule.processor.action", getAction(notification))
				.startSpan();

		// HTTP requests: the called app's flow becomes a child of this span (TraceContext.headers)
		if (HttpTracingUtils.isHttpRequester(notification)) {
			span.setAttribute("http.outgoing", true);
			transaction.setOutgoing(span);
		}

		// Set span details
		setSpanDetails(span, notification);

		// Store the span
		String spanId = getSpanId(notification);
		transactionStore.addSpan(transactionId, spanId, span);
	}

	/**
	 * Get the span ID from the notification.
	 */
	public static String getSpanId(MessageProcessorNotification notification) {
		return notification.getInfo().getComponent().getLocation().getLocation();
	}

	/**
	 * Populate span details at creation time.
	 */
	private static void setSpanDetails(Span span, MessageProcessorNotification notification) {
		span.setAttribute("mule.step.name", getStepName(notification));
		span.setAttribute("mule.step.location", getSpanId(notification));
	}

	/**
	 * Get the step name from the notification.
	 */
	public static String getStepName(MessageProcessorNotification notification) {
		Component component = notification.getComponent();
		Object nameAnnotation = component.getAnnotation(new QName(DOC_NAMESPACE, DOC_NAME));

		if (nameAnnotation == null) {
			return UNNAMED;
		}

		return nameAnnotation.toString();
	}

	/**
	 * Get the span action (same as type for now).
	 */
	private static String getAction(MessageProcessorNotification notification) {
		return getSpanType(notification);
	}

	/**
	 * Get the span subtype.
	 */
	private static String getSubType(MessageProcessorNotification notification) {
		return SUBTYPE;
	}

	/**
	 * Get the span type from the component identifier.
	 */
	private static String getSpanType(MessageProcessorNotification notification) {
		Component component = notification.getComponent();
		String name = component.getLocation().getComponentIdentifier().getIdentifier().getName();

		if (name == null) {
			return UNTYPED;
		}

		return name;
	}

	/**
	 * Get the transaction ID from the notification.
	 */
	private static String getTransactionId(MessageProcessorNotification notification) {
		return notification.getEvent().getCorrelationId();
	}

	/**
	 * End the span.
	 */
	public static void endSpan(TransactionStore transactionStore, MessageProcessorNotification notification) {
		String transactionId = getTransactionId(notification);
		String spanId = getSpanId(notification);

		Optional<Span> spanOpt = transactionStore.retrieveSpan(transactionId, spanId);
		if (spanOpt.isPresent()) {
			Span span = spanOpt.get();
			setFinalDetails(span, notification);
			transactionStore.getTransaction(transactionId).ifPresent(t -> t.clearOutgoing(span));
			span.end();
		} else {
			logger.debug("Could not find span {} for transaction {}", spanId, transactionId);
		}
	}

	/**
	 * Set final details on the span before ending.
	 */
	private static void setFinalDetails(Span span, MessageProcessorNotification notification) {
		// Can add final attributes here if needed
	}

	/**
	 * Get the flow name from a component location.
	 */
	public static String getFlowName(ComponentLocation location) {
		return location.getLocation().split("/")[0];
	}
}
