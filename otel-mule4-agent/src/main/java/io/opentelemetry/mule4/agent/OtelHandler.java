package io.opentelemetry.mule4.agent;

import java.util.Optional;

import org.mule.runtime.api.notification.ExceptionNotification;
import org.mule.runtime.api.notification.MessageProcessorNotification;
import org.mule.runtime.api.notification.PipelineMessageNotification;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import io.opentelemetry.mule4.agent.exception.ExceptionUtils;
import io.opentelemetry.mule4.agent.span.SpanUtils;
import io.opentelemetry.mule4.agent.tracing.HttpTracingUtils;
import io.opentelemetry.mule4.agent.transaction.OtelTransaction;
import io.opentelemetry.mule4.agent.transaction.TransactionStore;
import io.opentelemetry.mule4.agent.transaction.TransactionUtils;

/**
 * Main handler for Mule notifications.
 * Adapter called by flow event handlers and flow process step interceptors.
 */
public class OtelHandler {

	private static final Logger logger = LoggerFactory.getLogger(OtelHandler.class);

	// Store for all active transactions in flight
	static final TransactionStore transactionStore = new TransactionStore();  // package-private: TraceContextTest

	/**
	 * Transaction (root span) of a flow in flight, by correlation ID.
	 */
	public static Optional<OtelTransaction> getTransaction(String correlationId) {
		return correlationId == null ? Optional.empty() : transactionStore.getTransaction(correlationId);
	}

	/**
	 * Handle Mule process step start event.
	 */
	public static void handleProcessorStartEvent(MessageProcessorNotification notification) {
		logger.debug("Handling processor start event");
		SpanUtils.startSpan(transactionStore, notification);
	}

	/**
	 * Handle Mule process step end event.
	 */
	public static void handleProcessorEndEvent(MessageProcessorNotification notification) {
		logger.debug("Handling processor end event");
		SpanUtils.endSpan(transactionStore, notification);
	}

	/**
	 * Handle exception thrown in Mule flow.
	 */
	public static void handleExceptionEvent(ExceptionNotification notification) {
		logger.debug("Handling exception event");
		ExceptionUtils.captureException(transactionStore, notification);
	}

	/**
	 * Handle Mule flow start event.
	 */
	public static void handleFlowStartEvent(PipelineMessageNotification notification) {
		logger.debug("Handling flow start event");

		// no transaction for untraced requests (health checks): their processor spans are skipped with it
		if (TransactionUtils.isFirstEvent(transactionStore, notification) && !HttpTracingUtils.isUntraced(notification)) {
			TransactionUtils.startTransaction(transactionStore, notification);
		}
	}

	/**
	 * Handle Mule flow end event.
	 */
	public static void handleFlowEndEvent(PipelineMessageNotification notification) {
		logger.debug("Handling flow end event");
		TransactionUtils.endTransaction(transactionStore, notification);
	}
}
