package io.opentelemetry.mule4.agent.tracing;

import org.mule.extension.http.api.HttpRequestAttributes;
import org.mule.runtime.api.component.ComponentIdentifier;
import org.mule.runtime.api.metadata.TypedValue;
import org.mule.runtime.api.notification.MessageProcessorNotification;
import org.mule.runtime.api.notification.PipelineMessageNotification;
import org.mule.runtime.api.util.MultiMap;

import io.opentelemetry.mule4.agent.OtelStarter;
import io.opentelemetry.mule4.agent.transaction.OtelTransaction;

/**
 * Utilities for HTTP tracing and W3C Trace Context propagation.
 */
public class HttpTracingUtils {

	private static final String HTTP_REQUEST_NAMESPACE = "http://www.mulesoft.org/schema/mule/http";
	private static final String HTTP_REQUEST_NAME = "request";

	// W3C Trace Context headers
	public static final String TRACEPARENT_HEADER = "traceparent";
	public static final String TRACESTATE_HEADER = "tracestate";

	// Legacy Elastic APM header (for backwards compatibility)
	public static final String ELASTIC_APM_TRACEPARENT_HEADER = "elastic-apm-traceparent";

	/**
	 * Check if this is an HTTP event (has HttpRequestAttributes).
	 */
	public static boolean isHttpEvent(PipelineMessageNotification notification) {
		try {
			TypedValue<Object> attributes = extractAttributes(notification);
			return attributes.getDataType().getType() == HttpRequestAttributes.class;
		} catch (Exception e) {
			return false;
		}
	}

	/**
	 * Check if the notification has a remote parent (traceparent header).
	 */
	public static boolean hasRemoteParent(PipelineMessageNotification notification) {
		if (!isHttpEvent(notification)) {
			return false;
		}

		MultiMap<String, String> headers = getHttpHeaders(notification);
		return headers.containsKey(TRACEPARENT_HEADER)
				|| headers.containsKey(ELASTIC_APM_TRACEPARENT_HEADER);
	}

	/**
	 * Get the tracing header value for context extraction.
	 */
	public static String getTracingHeaderValue(String headerName, PipelineMessageNotification notification) {
		if (!isHttpEvent(notification)) {
			return null;
		}

		MultiMap<String, String> headers = getHttpHeaders(notification);

		// Try the requested header first
		if (headers.containsKey(headerName)) {
			return headers.get(headerName);
		}

		// For traceparent, also check the legacy elastic-apm-traceparent header
		if (TRACEPARENT_HEADER.equals(headerName) && headers.containsKey(ELASTIC_APM_TRACEPARENT_HEADER)) {
			return headers.get(ELASTIC_APM_TRACEPARENT_HEADER);
		}

		return null;
	}

	/**
	 * Get HTTP headers from the notification.
	 */
	/**
	 * Root span of an HTTP-triggered flow: method, path, listener route and tenant (X-Tenant-ID).
	 */
	public static void addRequestAttributes(OtelTransaction transaction, PipelineMessageNotification notification) {
		if (!isHttpEvent(notification)) {
			return;
		}
		HttpRequestAttributes attributes = (HttpRequestAttributes) extractAttributes(notification).getValue();
		transaction.addLabel("http.method", attributes.getMethod());
		transaction.addLabel("http.target", attributes.getRequestPath());
		transaction.addLabel("http.route", attributes.getListenerPath());
		String tenant = header(attributes.getHeaders(), "x-tenant-id");
		if (tenant != null && !tenant.isEmpty()) {
			transaction.addLabel("tenant.id", tenant.toLowerCase());
		}
	}

	/** Header value by name, ignoring case (the headers map keeps the sender's case unless the connector folds it). */
	private static String header(MultiMap<String, String> headers, String name) {
		for (String key : headers.keySet()) {
			if (name.equalsIgnoreCase(key)) {
				return headers.get(key);
			}
		}
		return null;
	}

	private static MultiMap<String, String> getHttpHeaders(PipelineMessageNotification notification) {
		HttpRequestAttributes attributes = (HttpRequestAttributes) extractAttributes(notification).getValue();
		return attributes.getHeaders();
	}

	/**
	 * Extract attributes from the notification.
	 */
	private static TypedValue<Object> extractAttributes(PipelineMessageNotification notification) {
		return notification.getEvent().getMessage().getAttributes();
	}

	/**
	 * Check if this notification is for an HTTP requester (outgoing HTTP call).
	 */
	public static boolean isHttpRequester(MessageProcessorNotification notification) {
		ComponentIdentifier identifier = notification.getInfo().getComponent().getIdentifier();
		String name = identifier.getName();
		String namespace = identifier.getNamespaceUri();

		return HTTP_REQUEST_NAME.equals(name) && HTTP_REQUEST_NAMESPACE.equals(namespace);
	}
}
