package io.opentelemetry.mule4.agent.exception;

import java.util.Optional;

import org.mule.runtime.api.notification.ExceptionNotification;

import io.opentelemetry.api.trace.StatusCode;
import io.opentelemetry.mule4.agent.transaction.OtelTransaction;
import io.opentelemetry.mule4.agent.transaction.TransactionStore;

/**
 * Handling of Exceptions thrown by flow steps.
 */
public class ExceptionUtils {

	private static final String ERROR_FLOW = "error.flow";
	private static final String ERROR_STEP = "error.step";

	/**
	 * Capture an exception on the transaction.
	 */
	public static void captureException(TransactionStore transactionStore, ExceptionNotification notification) {
		String transactionId = getTransactionId(notification);

		// Get the transaction
		Optional<OtelTransaction> transactionOpt = transactionStore.getTransaction(transactionId);
		if (!transactionOpt.isPresent()) {
			return;
		}

		OtelTransaction transaction = transactionOpt.get();

		// Ensure we only attach the exception once (rethrowing can cause multiple notifications)
		synchronized (transaction) {
			if (transaction.hasException()) {
				return;
			}

			// Record the exception on the span
			Throwable cause = getCause(notification);
			transaction.captureException(cause);

			// Add error context
			transaction.addLabel(ERROR_STEP, getStepName(notification));
			transaction.addLabel(ERROR_FLOW, getFlowName(notification));
			transaction.setException();

			// Update the transaction in the store
			transactionStore.updateTransaction(transactionId, transaction);
		}
	}

	/**
	 * Get the transaction ID from the notification.
	 */
	private static String getTransactionId(ExceptionNotification notification) {
		return notification.getEvent().getCorrelationId();
	}

	/**
	 * Get the flow name where the exception occurred.
	 */
	private static String getFlowName(ExceptionNotification notification) {
		return notification.getComponent().getLocation().getRootContainerName();
	}

	/**
	 * Get the step name where the exception occurred.
	 */
	private static String getStepName(ExceptionNotification notification) {
		return notification.getComponent().getLocation().getComponentIdentifier().getIdentifier().getName();
	}

	/**
	 * Get the exception cause.
	 */
	private static Throwable getCause(ExceptionNotification notification) {
		return notification.getException();
	}
}
