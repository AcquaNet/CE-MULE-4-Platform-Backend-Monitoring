package io.opentelemetry.mule4.agent;

import org.mule.runtime.api.notification.MessageProcessorNotification;
import org.mule.runtime.api.notification.MessageProcessorNotificationListener;
import org.springframework.stereotype.Component;

/**
 * Listener for Mule message processor notifications.
 * Handles processor (step) start and end events.
 */
@Component
public class OtelMessageProcessorNotificationListener implements MessageProcessorNotificationListener<MessageProcessorNotification> {

	@Override
	public boolean isBlocking() {
		return false;
	}

	@Override
	public void onNotification(MessageProcessorNotification notification) {
		switch (notification.getAction().getActionId()) {
			case MessageProcessorNotification.MESSAGE_PROCESSOR_PRE_INVOKE:
				OtelHandler.handleProcessorStartEvent(notification);
				break;
			case MessageProcessorNotification.MESSAGE_PROCESSOR_POST_INVOKE:
				OtelHandler.handleProcessorEndEvent(notification);
				break;
			default:
				// Ignore other actions
				break;
		}
	}
}
