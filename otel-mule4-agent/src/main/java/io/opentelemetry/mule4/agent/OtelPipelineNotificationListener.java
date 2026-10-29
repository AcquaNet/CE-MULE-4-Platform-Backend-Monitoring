package io.opentelemetry.mule4.agent;

import org.mule.runtime.api.notification.PipelineMessageNotification;
import org.mule.runtime.api.notification.PipelineMessageNotificationListener;
import org.springframework.stereotype.Component;

/**
 * Listener for Mule pipeline (flow) notifications.
 * Handles flow start and end events.
 */
@Component
public class OtelPipelineNotificationListener implements PipelineMessageNotificationListener<PipelineMessageNotification> {

	@Override
	public boolean isBlocking() {
		return false;
	}

	@Override
	public void onNotification(PipelineMessageNotification notification) {
		switch (notification.getAction().getActionId()) {
			case PipelineMessageNotification.PROCESS_START:
				OtelHandler.handleFlowStartEvent(notification);
				break;
			case PipelineMessageNotification.PROCESS_COMPLETE:
			case PipelineMessageNotification.PROCESS_END:
				OtelHandler.handleFlowEndEvent(notification);
				break;
			default:
				// Ignore other actions
				break;
		}
	}
}
