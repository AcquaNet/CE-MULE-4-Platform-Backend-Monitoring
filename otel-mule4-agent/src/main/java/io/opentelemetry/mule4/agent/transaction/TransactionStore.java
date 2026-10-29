package io.opentelemetry.mule4.agent.transaction;

import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

import io.opentelemetry.api.trace.Span;

/**
 * Store for transactions (root spans) in flight.
 * Thread-safe storage for active traces and their child spans.
 */
public class TransactionStore {

	/**
	 * Wrapper to store a root span (transaction) and its child spans.
	 */
	private static class TransactionAndSpans {
		private OtelTransaction transaction;
		public Map<String, Span> spanMap = new ConcurrentHashMap<>();

		public TransactionAndSpans(OtelTransaction transaction) {
			this.transaction = transaction;
		}

		public OtelTransaction getTransaction() {
			return this.transaction;
		}

		public void setTransaction(OtelTransaction transaction) {
			this.transaction = transaction;
		}
	}

	// Possible concurrent access to the same transaction
	private Map<String, TransactionAndSpans> transactionMap = new ConcurrentHashMap<>();

	/**
	 * Check if a transaction exists for the given ID.
	 */
	public boolean isTransactionPresent(String transactionId) {
		return transactionMap.containsKey(transactionId);
	}

	/**
	 * Store a new transaction.
	 */
	public void storeTransaction(String transactionId, OtelTransaction transaction) {
		transactionMap.put(transactionId, new TransactionAndSpans(transaction));
	}

	/**
	 * Retrieve and remove the transaction from the store.
	 */
	public Optional<OtelTransaction> retrieveTransaction(String transactionId) {
		TransactionAndSpans removed = transactionMap.remove(transactionId);
		if (removed == null) {
			return Optional.empty();
		}
		return Optional.of(removed.getTransaction());
	}

	/**
	 * Get the transaction without removing it from the store.
	 */
	public Optional<OtelTransaction> getTransaction(String transactionId) {
		TransactionAndSpans transactionAndSpans = transactionMap.get(transactionId);
		if (transactionAndSpans == null) {
			return Optional.empty();
		}
		return Optional.ofNullable(transactionAndSpans.getTransaction());
	}

	/**
	 * Add a child span to a transaction.
	 */
	public void addSpan(String transactionId, String spanId, Span span) {
		TransactionAndSpans transactionAndSpans = transactionMap.get(transactionId);
		if (transactionAndSpans != null) {
			synchronized (transactionAndSpans.spanMap) {
				transactionAndSpans.spanMap.put(spanId, span);
			}
		}
	}

	/**
	 * Retrieve and remove a span from the store.
	 */
	public Optional<Span> retrieveSpan(String transactionId, String spanId) {
		TransactionAndSpans transactionAndSpans = transactionMap.get(transactionId);
		if (transactionAndSpans == null) {
			return Optional.empty();
		}
		return Optional.ofNullable(transactionAndSpans.spanMap.remove(spanId));
	}

	/**
	 * Update an existing transaction.
	 */
	public void updateTransaction(String transactionId, OtelTransaction transaction) {
		TransactionAndSpans transactionAndSpans = transactionMap.get(transactionId);
		if (transactionAndSpans != null) {
			transactionAndSpans.setTransaction(transaction);
		}
	}
}
