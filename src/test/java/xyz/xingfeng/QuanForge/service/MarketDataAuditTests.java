package xyz.xingfeng.QuanForge.service;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import xyz.xingfeng.QuanForge.entity.Kline1m;
import xyz.xingfeng.QuanForge.repository.Kline1mRepository;

import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/** Pure mocks: no Spring context, credentials, HTTP or production database. */
class MarketDataAuditTests {
    @Test void oldButContinuousBarsMustNotBeAcceptedAsCurrentMarket() {
        long now = 600_000;
        org.assertj.core.api.Assertions.assertThatThrownBy(() -> AiToolRegistry.closedKlines(
                new JSONArray().put(row(0,100)).put(row(60_000,101)), "1", now,100))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test void invalidOhlcAndUnalignedTimestampMustBeRejected() {
        org.assertj.core.api.Assertions.assertThatThrownBy(() -> AiToolRegistry.closedKlines(
                new JSONArray().put(row(1,100)),"1",120000,100)).isInstanceOf(IllegalStateException.class);
        org.assertj.core.api.Assertions.assertThatThrownBy(() -> AiToolRegistry.closedKlines(
                new JSONArray().put(row(60000,999)),"1",120000,100)).isInstanceOf(IllegalStateException.class);
    }
    private static JSONArray row(long ts, double close) {
        return new JSONArray().put(Long.toString(ts)).put("100").put("200").put("1")
                .put(Double.toString(close)).put("10").put("1000");
    }

    private static String response(JSONArray rows) throws Exception {
        return new JSONObject().put("retCode", 0).put("result", new JSONObject().put("list", rows)).toString();
    }

    @Test
    void historyRevisitsRequestedWindowAndNeverStoresOpenBar() throws Exception {
        Kline1mRepository repo = mock(Kline1mRepository.class);
        BybitService bybit = mock(BybitService.class);
        long currentMinute = System.currentTimeMillis() / 60_000 * 60_000;
        LocalDateTime from = LocalDateTime.ofInstant(Instant.ofEpochMilli(currentMinute - 300_000), ZoneId.systemDefault());
        when(repo.latestOpenTime("BTCUSDT")).thenReturn(from.plusMinutes(3));
        when(bybit.getPublicRaw(eq("/v5/market/kline"), anyMap())).thenReturn(response(new JSONArray()
                .put(row(currentMinute, 999)).put(row(currentMinute - 60_000, 101))));
        new KlineHistoryService(repo, bybit).download("BTCUSDT", from).join();
        ArgumentCaptor<Map<String, String>> request = ArgumentCaptor.forClass(Map.class);
        verify(bybit).getPublicRaw(eq("/v5/market/kline"), request.capture());
        assertThat(Long.parseLong(request.getValue().get("start"))).isEqualTo(currentMinute - 300_000);
        ArgumentCaptor<List<Kline1m>> saved = ArgumentCaptor.forClass(List.class);
        verify(repo).saveAll(saved.capture());
        assertThat(saved.getValue()).hasSize(1);
        assertThat(saved.getValue().get(0).getClose()).isEqualTo(101);
    }

    @Test
    void aiIndicatorsExcludeUnfinishedCandle() throws Exception {
        BybitService bybit = mock(BybitService.class);
        long currentMinute = System.currentTimeMillis() / 60_000 * 60_000;
        JSONArray rows = new JSONArray().put(row(currentMinute, 999));
        for (int i = 1; i <= 150; i++) rows.put(row(currentMinute - i * 60_000, 100));
        when(bybit.getPublicRaw(anyString(), anyMap())).thenReturn(response(rows));
        AiToolRegistry registry = new AiToolRegistry(bybit, null, null, null, "http://unused");
        JSONObject result = new JSONObject(registry.execute("get_indicators",
                new JSONObject().put("symbol", "BTCUSDT").put("interval", "1")));
        assertThat(result.has("error")).isFalse();
        assertThat(result.getDouble("lastPrice")).isEqualTo(100);
        assertThat(result.getDouble("EMA7")).isEqualTo(100);
    }

    @Test
    void emaDoesNotInventZeroWhenInsufficientHistory() {
        assertThat(IndicatorMath.emaLast(new double[] {100, 101}, 7)).isNaN();
    }

    @Test
    void duplicateAndOutOfOrderBarsNormalizeButMissingBarsRejectIndicators() throws Exception {
        BybitService bybit = mock(BybitService.class);
        long t = System.currentTimeMillis() / 60_000 * 60_000 - 180_000;
        when(bybit.getPublicRaw(anyString(), anyMap())).thenReturn(response(new JSONArray()
                .put(row(t, 100)).put(row(t + 60_000, 101)).put(row(t, 100))));
        AiToolRegistry registry = new AiToolRegistry(bybit, null, null, null, "http://unused");
        JSONObject args = new JSONObject().put("symbol", "BTCUSDT").put("interval", "1");
        JSONObject normalized = new JSONObject(registry.execute("get_kline", args));
        assertThat(normalized.getInt("count")).isEqualTo(2);
        assertThat(normalized.getJSONArray("klines").getJSONArray(0).getLong(0)).isEqualTo(t + 60_000);
        when(bybit.getPublicRaw(anyString(), anyMap())).thenReturn(response(new JSONArray()
                .put(row(t, 100)).put(row(t + 120_000, 102))));
        assertThat(new JSONObject(registry.execute("get_kline", args)).getString("error")).contains("gap");
    }

    @Test
    void monthlyClosureUsesCalendarMonthAndUtc() {
        long february = Instant.parse("2026-02-01T00:00:00Z").toEpochMilli();
        assertThat(AiToolRegistry.candleEnd(february, "M"))
                .isEqualTo(Instant.parse("2026-03-01T00:00:00Z").toEpochMilli());
    }

    @Test
    void fallbackAndTriggerInputsAlsoExcludeUnfinishedCandle() throws Exception {
        BybitService bybit = mock(BybitService.class);
        long t = System.currentTimeMillis() / 900_000 * 900_000;
        when(bybit.getPublicRaw(anyString(), anyMap())).thenReturn(response(new JSONArray()
                .put(row(t, 999)).put(row(t - 900_000, 100)).put(row(t - 1_800_000, 99))));
        AiAnalysisService analysis = new AiAnalysisService(null, bybit, null, null, null, null, null, null);
        // This is the exact loader used by 15m trigger, 5m trigger and fixed-context fallback.
        var method = AiAnalysisService.class.getDeclaredMethod("fetchKlines", String.class, String.class, int.class);
        method.setAccessible(true);
        double[][] prices = (double[][]) method.invoke(analysis, "BTCUSDT", "15", 100);
        assertThat(prices[3]).containsExactly(99, 100);
    }
}
