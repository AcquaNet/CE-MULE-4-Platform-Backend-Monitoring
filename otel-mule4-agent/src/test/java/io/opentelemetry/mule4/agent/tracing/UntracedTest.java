package io.opentelemetry.mule4.agent.tracing;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;
import org.mule.runtime.api.util.MultiMap;

/** X-Untraced (the gateway's health checks) skips the trace, whatever the header's case or value; others are traced. */
public class UntracedTest {

	private static MultiMap<String, String> headers(String... kv) {
		MultiMap<String, String> m = new MultiMap<>();
		for (int i = 0; i < kv.length; i += 2) {
			m.put(kv[i], kv[i + 1]);
		}
		return m;
	}

	@Test
	public void healthChecksAreNotTraced() {
		assertTrue(HttpTracingUtils.isUntraced(headers("X-Untraced", "health-check")));
		assertTrue(HttpTracingUtils.isUntraced(headers("x-untraced", "")));
	}

	@Test
	public void ordinaryRequestsAreTraced() {
		assertFalse(HttpTracingUtils.isUntraced(headers()));
		assertFalse(HttpTracingUtils.isUntraced(headers("Authorization", "Bearer x", "X-Tenant-ID", "acme")));
	}
}
