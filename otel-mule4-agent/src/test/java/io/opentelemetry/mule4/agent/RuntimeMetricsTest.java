package io.opentelemetry.mule4.agent;

import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import java.util.Set;
import java.util.stream.Collectors;

import org.junit.Test;

import io.opentelemetry.sdk.OpenTelemetrySdk;
import io.opentelemetry.sdk.metrics.SdkMeterProvider;
import io.opentelemetry.sdk.metrics.data.MetricData;
import io.opentelemetry.sdk.testing.exporter.InMemoryMetricReader;

/** JVM metrics the agent registers (OtelStarter.startRuntimeMetrics): the series the Grafana "Mule JVM" dashboard uses. */
public class RuntimeMetricsTest {

	@Test
	public void jvmMetricsAreRecorded() throws Exception {
		InMemoryMetricReader reader = InMemoryMetricReader.create();
		OpenTelemetrySdk sdk = OpenTelemetrySdk.builder()
				.setMeterProvider(SdkMeterProvider.builder().registerMetricReader(reader).build()).build();
		AutoCloseable metrics = OtelStarter.startRuntimeMetrics(sdk);
		assertNotNull(metrics);
		try {
			System.gc();  // at least one jvm.gc.duration point
			Set<String> names = reader.collectAllMetrics().stream().map(MetricData::getName).collect(Collectors.toSet());
			for (String n : new String[] {"jvm.memory.used", "jvm.memory.limit", "jvm.thread.count", "jvm.class.count",
					"jvm.cpu.recent_utilization"}) {
				assertTrue(n + " in " + names, names.contains(n));
			}
		} finally {
			metrics.close();
			sdk.close();
		}
	}
}
