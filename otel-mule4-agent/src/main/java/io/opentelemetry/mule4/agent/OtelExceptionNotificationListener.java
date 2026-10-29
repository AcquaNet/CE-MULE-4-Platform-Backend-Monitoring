package io.opentelemetry.mule4.agent;

import org.mule.runtime.api.notification.ExceptionNotification;
import org.mule.runtime.api.notification.ExceptionNotificationListener;
import org.springframework.stereotype.Component;

/**
 * Listener for Mule exception notifications.
 * Handles exceptions thrown during flow execution.
 */
@Component
public class OtelExceptionNotificationListener implements ExceptionNotificationListener {

	@Override
	public boolean isBlocking() {
		return false;
	}

	@Override
	public void onNotification(ExceptionNotification notification) {
		OtelHandler.handleExceptionEvent(notification);
	}
}
