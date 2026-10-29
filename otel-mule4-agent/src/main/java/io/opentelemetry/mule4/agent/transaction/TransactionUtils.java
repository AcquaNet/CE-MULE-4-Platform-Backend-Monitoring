package io.opentelemetry.mule4.agent.transaction;

import java.lang.reflect.Field;
import java.util.Optional;

import org.mule.runtime.api.event.Event;
import org.mule.runtime.api.metadata.TypedValue;
import org.mule.runtime.api.notification.PipelineMessageNotification;
import org.mule.runtime.core.api.event.CoreEvent;
import org.slf4j.MDC;

import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanKind;
import io.opentelemetry.api.trace.StatusCode;
import io.opentelemetry.context.Context;
import io.opentelemetry.context.propagation.TextMapGetter;
import io.opentelemetry.mule4.agent.OtelStarter;
import io.opentelemetry.mule4.agent.tracing.HttpTracingUtils;

/**
 * Handling of Transaction (root span) starts and ends.
 */
public class TransactionUtils {

	private static final String TRANSACTION_ID = "transaction.id";
	private static final String TRACE_ID = "trace.id";
	private static final String SPAN_ID = "span.id";

	/**
	 * Is this notification related to a newly started flow?
	 * (i.e., there is no transaction yet in the transactionStore)
	 */
	public static boolean isFirstEvent(TransactionStore transactionStore, PipelineMessageNotification notification) {
		Optional<String> transactionId = getTransactionId(notification);
		return transactionId.isPresent() && !transactionStore.isTransactionPresent(transactionId.get());
	}

	/**
	 * Start a new transaction (root span).
	 */
	public static void startTransaction(TransactionStore transactionStore, PipelineMessageNotification notification) {
		Span span;

		// Check if it has parent trace-id from incoming request
		if (hasRemoteParent(notification)) {
			Context extractedContext = extractRemoteContext(notification);
			span = OtelStarter.getTracer()
					.spanBuilder(getFlowName(notification))
					.setParent(extractedContext)
					.setSpanKind(SpanKind.SERVER)
					.startSpan();
		} else {
			span = OtelStarter.getTracer()
					.spanBuilder(getFlowName(notification))
					.setSpanKind(SpanKind.SERVER)
					.startSpan();
		}

		// Wrap in OtelTransaction and populate details
		OtelTransaction transaction = new OtelTransaction(span);
		HttpTracingUtils.addRequestAttributes(transaction, notification);
		populateTransactionDetails(transaction, notification);

		// Store the transaction
		getTransactionId(notification).ifPresent(id ->
				transactionStore.storeTransaction(id, transaction));

		// Populate MDC for logs correlation
		MDC.put(TRACE_ID, transaction.getTraceId());
		MDC.put(TRANSACTION_ID, transaction.getId());
		MDC.put(SPAN_ID, transaction.getId());
	}

	/**
	 * Populate transaction details from the notification.
	 */
	private static void populateTransactionDetails(OtelTransaction transaction, PipelineMessageNotification notification) {
		String flowName = getFlowName(notification);
		transaction.setName(flowName);
		transaction.setFlowName(flowName);
		transaction.setType("request");

		getTransactionId(notification).ifPresent(id ->
				transaction.addLabel("correlationId", id));
	}

	/**
	 * Get the flow name from the notification.
	 */
	private static String getFlowName(PipelineMessageNotification notification) {
		return notification.getResourceIdentifier();
	}

	/**
	 * Retrieve the transaction ID (correlation ID) from the notification.
	 */
	private static Optional<String> getTransactionId(PipelineMessageNotification notification) {
		Event event = notification.getEvent();

		if (event != null) {
			return Optional.of(event.getCorrelationId());
		}

		// If event == null, this must be an exception case
		Exception e = notification.getInfo().getException();
		if (e == null) {
			return Optional.empty();
		}

		// Workaround to get the event from MessagingException
		try {
			Field f = e.getClass().getDeclaredField("processedEvent");
			f.setAccessible(true);
			CoreEvent coreEvent = (CoreEvent) f.get(e);
			if (coreEvent != null) {
				return Optional.of(coreEvent.getCorrelationId());
			}
		} catch (NoSuchFieldException | SecurityException | IllegalAccessException ex) {
			// Ignore - field not found
		}

		return Optional.empty();
	}

	/**
	 * Extract remote context from W3C traceparent header.
	 */
	private static Context extractRemoteContext(PipelineMessageNotification notification) {
		return OtelStarter.getOpenTelemetry()
				.getPropagators()
				.getTextMapPropagator()
				.extract(Context.current(), notification, new TextMapGetter<PipelineMessageNotification>() {
					@Override
					public Iterable<String> keys(PipelineMessageNotification carrier) {
						return java.util.Arrays.asList("traceparent", "tracestate");
					}

					@Override
					public String get(PipelineMessageNotification carrier, String key) {
						return HttpTracingUtils.getTracingHeaderValue(key, carrier);
					}
				});
	}

	/**
	 * Check if the notification has a remote parent (traceparent header).
	 */
	private static boolean hasRemoteParent(PipelineMessageNotification notification) {
		return HttpTracingUtils.isHttpEvent(notification) && HttpTracingUtils.hasRemoteParent(notification);
	}

	/**
	 * End the transaction.
	 */
	public static void endTransaction(TransactionStore transactionStore, PipelineMessageNotification notification) {
		// Only end transactions for top-level flows or exceptions
		if (!isEndOfTopFlowOrException(transactionStore, notification)) {
			return;
		}

		Optional<String> transactionId = getTransactionId(notification);
		if (!transactionId.isPresent()) {
			return;
		}

		Optional<OtelTransaction> transactionOpt = transactionStore.retrieveTransaction(transactionId.get());
		if (transactionOpt.isPresent()) {
			OtelTransaction transaction = transactionOpt.get();
			populateFinalTransactionDetails(transaction, notification);
			transaction.end();
		}

		// Clean MDC
		MDC.remove(TRACE_ID);
		MDC.remove(TRANSACTION_ID);
		MDC.remove(SPAN_ID);
	}

	/**
	 * Check if this is the end of the top-level flow or an exception.
	 */
	private static boolean isEndOfTopFlowOrException(TransactionStore transactionStore, PipelineMessageNotification notification) {
		Optional<String> transactionId = getTransactionId(notification);
		if (!transactionId.isPresent()) {
			return false;
		}

		Optional<OtelTransaction> transactionOpt = transactionStore.getTransaction(transactionId.get());
		if (!transactionOpt.isPresent()) {
			return false;
		}

		OtelTransaction transaction = transactionOpt.get();
		return transaction.hasException() || transaction.getFlowName().equals(getFlowName(notification));
	}

	/**
	 * Populate final transaction details before ending.
	 */
	/**
	 * http.status_code for HTTP flows: the listener sets the real code after the flow ends, so use what
	 * the flow decided (vars.httpStatus, set by APIkit error handlers), else 500 on error, else 200.
	 */
	private static void populateFinalTransactionDetails(OtelTransaction transaction, PipelineMessageNotification notification) {
		if (!transaction.getLabel("http.method").isPresent()) {
			return;
		}
		Event event = notification.getEvent();
		TypedValue<?> status = event == null ? null : event.getVariables().get("httpStatus");
		boolean failed = notification.getInfo().getException() != null;
		long code = failed ? 500 : 200;
		if (status != null && status.getValue() != null) {
			try {
				code = Long.parseLong(String.valueOf(status.getValue()));
			} catch (NumberFormatException e) {
				// keep the default
			}
		}
		transaction.getSpan().setAttribute("http.status_code", code);
		if (code >= 500 || failed) {
			transaction.getSpan().setStatus(StatusCode.ERROR);
		}
	}
}
