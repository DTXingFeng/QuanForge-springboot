package xyz.xingfeng.QuanForge.service;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.util.ReflectionTestUtils;
import xyz.xingfeng.QuanForge.entity.AiAdviceTrack;
import xyz.xingfeng.QuanForge.entity.AiAlert;
import xyz.xingfeng.QuanForge.entity.AiConfig;
import xyz.xingfeng.QuanForge.repository.AiAdviceTrackRepository;

import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/** Offline regressions: no Spring context, credentials, scheduler or external HTTP. */
class ExecutionSafetyTests {
    BybitService bybit;
    AiAdviceTrackRepository repository;
    DemoOrderExecutor executor;
    AiConfigService configs;
    AiAdviceTracker tracker;

    @BeforeEach void setup() {
        bybit = mock(BybitService.class);
        repository = mock(AiAdviceTrackRepository.class);
        executor = mock(DemoOrderExecutor.class);
        configs = mock(AiConfigService.class);
        AiConfig cfg = new AiConfig();
        cfg.setAutoOrderEnabled(true);
        when(configs.getConfig()).thenReturn(cfg);
        tracker = new AiAdviceTracker(repository, bybit, mock(TelegramBotService.class), executor, configs);
    }

    AiAdviceTrack demo(String status) {
        AiAdviceTrack t = new AiAdviceTrack();
        t.setSymbol("ALTUSDT"); t.setAction("BUY"); t.setExecMode("DEMO");
        t.setStatus(status); t.setOrderId("entry-1"); t.setEntry(100.0);
        t.setTakeProfit(110.0); t.setStopLoss(95.0); t.setQty(1.0); t.setActualEntry(100.0);
        ReflectionTestUtils.setField(t, "createdAt", LocalDateTime.now().minusHours(4));
        t.setEnteredAt(LocalDateTime.now().minusHours(3));
        return t;
    }

    @Test void acceptedButLostResponseMustNeverBecomePaper() {
        AiAlert alert = new AiAlert(); alert.setSymbol("ALTUSDT"); ReflectionTestUtils.setField(alert,"id",41L);
        when(executor.placeEntry(anyString(),anyString(),anyDouble(),anyDouble(),anyDouble(),anyDouble(),anyInt(),anyString()))
                .thenThrow(new IllegalStateException("accepted; response lost"));
        tracker.track(alert,"BUY",100,95,110);
        ArgumentCaptor<AiAdviceTrack> saved=ArgumentCaptor.forClass(AiAdviceTrack.class);
        verify(repository,atLeastOnce()).saveAndFlush(saved.capture());
        assertThat(saved.getValue().getExecMode()).isEqualTo("DEMO");
        assertThat(saved.getValue().getStatus()).isEqualTo("PENDING");
    }

    @Test void failedIntentCommitMustNotReachExchange() {
        when(repository.saveAndFlush(any())).thenThrow(new org.springframework.dao.DataAccessResourceFailureException("disk full"));
        AiAlert alert=new AiAlert(); alert.setSymbol("ALTUSDT");
        tracker.track(alert,"BUY",100,95,110);
        verifyNoInteractions(executor);
    }

    @Test void journalMustRecordIntentBeforeRequestAndAckMustRemainUnconfirmed() {
        ExecutionJournal journal=mock(ExecutionJournal.class);
        ReflectionTestUtils.setField(tracker,"executionJournal",journal);
        when(repository.saveAndFlush(any())).thenAnswer(call -> {
            AiAdviceTrack value=call.getArgument(0);ReflectionTestUtils.setField(value,"id",12L);return value;
        });
        when(executor.placeEntry(anyString(),anyString(),anyDouble(),anyDouble(),anyDouble(),anyDouble(),anyInt(),anyString()))
                .thenReturn(new DemoOrderExecutor.Placement("ack",1,200));
        AiAlert alert=new AiAlert();alert.setSymbol("ALTUSDT");
        tracker.track(alert,"BUY",100,95,110);
        var order=inOrder(repository,journal,executor);
        order.verify(repository).saveAndFlush(any());
        order.verify(journal).record(any(),eq("ENTRY_INTENT"),anyString());
        order.verify(executor).placeEntry(anyString(),anyString(),anyDouble(),anyDouble(),anyDouble(),anyDouble(),anyInt(),anyString());
        order.verify(journal).record(any(),eq("ENTRY_ACK"),contains("unconfirmed"));
    }

    @Test void unresolvedDemoMustBlockOtherSymbolsEvenWhenAutoOrderingIsDisabled() {
        AiAdviceTrack pending=demo("PENDING"); pending.setOrderId(null);
        when(repository.findByStatusIn(anyList())).thenReturn(List.of(pending));
        configs.getConfig().setAutoOrderEnabled(false);
        AiAlert alert=new AiAlert(); alert.setSymbol("OTHERUSDT");
        tracker.track(alert,"SELL",100,105,90);
        verifyNoInteractions(executor);
        verify(repository,never()).save(any());
        verify(repository,never()).saveAndFlush(any());
    }

    @Test void linkRecoveryMustRejectUnrelatedExchangeRows() {
        DemoOrderExecutor real=new DemoOrderExecutor(bybit);
        when(bybit.getDemoRaw(anyString(),anyString(),anyMap())).thenReturn(
                "{\"retCode\":0,\"result\":{\"list\":[{\"symbol\":\"OTHERUSDT\",\"orderLinkId\":\"ours\",\"orderId\":\"foreign\"}]}}");
        assertThatThrownBy(() -> real.orderDetailByLink("ALTUSDT","ours")).isInstanceOf(IllegalStateException.class);
    }

    @Test void managementNoteMustNotDisableTtlExit() throws Exception {
        AiAdviceTrack t = demo("TRACKING");
        t.setNote("动态管理调整: 收紧止损");
        when(repository.findByStatusIn(anyList())).thenReturn(List.of(t));
        when(executor.position("ALTUSDT")).thenReturn(new JSONObject().put("side","Buy").put("size","1"));
        tracker.settle();
        verify(executor).marketClose("ALTUSDT", "Buy", 1.0);
        assertThat(t.getStatus()).isEqualTo("TRACKING");
    }

    @Test void failedReverseMustKeepOldPositionManagedAndBlockNewEntry() throws Exception {
        AiAdviceTrack t = demo("TRACKING");
        when(repository.findBySymbolAndStatusIn(eq("ALTUSDT"), anyList())).thenReturn(List.of(t));
        when(executor.position("ALTUSDT")).thenReturn(new JSONObject().put("side","Buy").put("size","1"));
        doThrow(new IllegalStateException("timeout")).when(executor).marketClose(anyString(),anyString(),anyDouble());
        AiAlert alert = new AiAlert(); alert.setSymbol("ALTUSDT");
        tracker.track(alert,"SELL",100,105,90);
        assertThat(t.getStatus()).isEqualTo("TRACKING");
        verify(executor, never()).placeEntry(anyString(),anyString(),anyDouble(),anyDouble(),anyDouble(),anyDouble(),anyInt());
    }

    @Test void cancelAcknowledgementWithoutFinalOrderStateMustNotExpirePending() throws Exception {
        AiAdviceTrack t = demo("PENDING");
        t.setEnteredAt(null);
        when(repository.findByStatusIn(anyList())).thenReturn(List.of(t));
        when(executor.orderDetail("ALTUSDT","entry-1")).thenReturn(new JSONObject().put("orderStatus","New").put("cumExecQty","0"));
        when(executor.cancel("ALTUSDT","entry-1")).thenReturn(true);
        tracker.settle();
        assertThat(t.getStatus()).isEqualTo("PENDING");
    }

    @Test void buyLimitMustNotFillOnCandleWhollyAboveLimit() throws Exception {
        AiAdviceTrack t = demo("PENDING"); t.setExecMode("PAPER"); t.setEnteredAt(null);
        ReflectionTestUtils.setField(t,"createdAt",LocalDateTime.now().minusMinutes(3));
        long ms=LocalDateTime.now().minusMinutes(2).atZone(ZoneId.systemDefault()).toInstant().toEpochMilli();
        ReflectionTestUtils.invokeMethod(tracker,"settleOne",t,List.of(new double[]{ms,105,101,104}));
        assertThat(t.getStatus()).isEqualTo("PENDING");
    }

    @Test void sellLimitMustNotFillOnCandleWhollyBelowLimit() throws Exception {
        AiAdviceTrack t = demo("PENDING"); t.setExecMode("PAPER"); t.setAction("SELL"); t.setEnteredAt(null);
        ReflectionTestUtils.setField(t,"createdAt",LocalDateTime.now().minusMinutes(3));
        long ms=LocalDateTime.now().minusMinutes(2).atZone(ZoneId.systemDefault()).toInstant().toEpochMilli();
        ReflectionTestUtils.invokeMethod(tracker,"settleOne",t,List.of(new double[]{ms,99,95,96}));
        assertThat(t.getStatus()).isEqualTo("PENDING");
    }

    @Test void entryMustCarryExchangeProtectionFromSubmission() throws Exception {
        DemoOrderExecutor realExecutor = new DemoOrderExecutor(bybit);
        when(bybit.getPublicRaw(eq("/v5/market/instruments-info"),anyMap())).thenReturn(new JSONObject().put("retCode",0).put("result",new JSONObject().put("list",new JSONArray().put(new JSONObject()
                .put("lotSizeFilter",new JSONObject().put("minOrderQty","0.01").put("qtyStep","0.01").put("minNotionalValue","1"))
                .put("priceFilter",new JSONObject().put("tickSize","0.1"))
                .put("leverageFilter",new JSONObject().put("maxLeverage","100"))))).toString());
        when(bybit.getDemoRaw(anyString(),eq("/v5/account/wallet-balance"),anyMap())).thenReturn("{\"retCode\":0,\"result\":{\"list\":[{\"totalEquity\":\"1000\"}]}}");
        when(bybit.getPublicRaw(eq("/v5/market/tickers"),anyMap())).thenReturn("{\"retCode\":0,\"result\":{\"list\":[{\"lastPrice\":\"100\"}]}}");
        when(bybit.postDemo(anyString(),anyString(),anyString())).thenReturn("{\"retCode\":0,\"result\":{\"orderId\":\"entry-1\"}}");
        realExecutor.placeEntry("ALTUSDT","BUY",100,110,95,5,10);
        ArgumentCaptor<String> body=ArgumentCaptor.forClass(String.class);
        verify(bybit).postDemo(anyString(),eq("/v5/order/create"),body.capture());
        JSONObject sent=new JSONObject(body.getValue());
        assertThat(sent.optString("stopLoss")).isEqualTo("95");
        assertThat(sent.optString("takeProfit")).isEqualTo("110");
        assertThat(sent.optString("tpslMode")).isEqualTo("Full");
    }

    @Test void takeProfitAloneMustNotHideAnUnprotectedOrphan() throws Exception {
        when(executor.positionsUsdt()).thenReturn(new JSONArray().put(new JSONObject()
                .put("symbol","ALTUSDT").put("size","1").put("side","Buy")
                .put("avgPrice","100").put("markPrice","99")
                .put("takeProfit","110").put("stopLoss","0")));
        new OrphanPositionGuard(executor,mock(TelegramBotService.class)).sweep();
        verify(executor).setProtectiveStop(eq("ALTUSDT"),doubleThat(x -> x > 0 && x < 99));
    }

    @Test void filledCancellationRaceMustRetainAndProtectPosition() throws Exception {
        AiAdviceTrack t=demo("PENDING"); t.setEnteredAt(null);
        when(repository.findByStatusIn(anyList())).thenReturn(List.of(t));
        when(executor.orderDetail("ALTUSDT","entry-1")).thenReturn(
                new JSONObject().put("orderStatus","New").put("cumExecQty","0"),
                new JSONObject().put("orderStatus","Filled").put("cumExecQty","1").put("avgPrice","100"));
        tracker.settle();
        assertThat(t.getStatus()).isEqualTo("TRACKING");
        verify(executor).setTradingStop("ALTUSDT","BUY",110,95);
    }

    @Test void duplicateFilledResponseCannotCreateAnotherEntryOrResetEntryTime() throws Exception {
        AiAdviceTrack t=demo("PENDING"); t.setEnteredAt(null);
        when(repository.findByStatusIn(anyList())).thenReturn(List.of(t));
        when(executor.orderDetail("ALTUSDT","entry-1")).thenReturn(
                new JSONObject().put("orderStatus","Filled").put("cumExecQty","1").put("avgPrice","100"));
        when(executor.position("ALTUSDT")).thenReturn(new JSONObject().put("side","Buy").put("size","1"));
        tracker.settle();
        LocalDateTime entered=t.getEnteredAt();
        tracker.settle();
        assertThat(t.getEnteredAt()).isEqualTo(entered);
        verify(executor,times(1)).setTradingStop("ALTUSDT","BUY",110,95);
        verify(executor,never()).placeEntry(anyString(),anyString(),anyDouble(),anyDouble(),anyDouble(),anyDouble(),anyInt());
    }

    @Test void timedOutTtlCloseIsRetriedAndNeverSettledBeforeExchangeConfirmation() throws Exception {
        AiAdviceTrack t=demo("TRACKING");
        when(repository.findByStatusIn(anyList())).thenReturn(List.of(t));
        when(executor.position("ALTUSDT")).thenReturn(
                new JSONObject().put("side","Buy").put("size","1"),
                new JSONObject().put("side","Buy").put("size","1"), null);
        doThrow(new IllegalStateException("timeout")).doNothing()
                .when(executor).marketClose("ALTUSDT","Buy",1.0);
        tracker.settle();
        assertThat(t.getStatus()).isEqualTo("TRACKING");
        tracker.settle();
        assertThat(t.getStatus()).isEqualTo("TRACKING");
        when(executor.closedPnlSince(eq("ALTUSDT"),anyLong()))
                .thenReturn(new DemoOrderExecutor.ClosedResult(-5,1,95));
        tracker.settle();
        assertThat(t.getStatus()).isEqualTo("LOSS");
        verify(executor,times(2)).marketClose("ALTUSDT","Buy",1.0);
    }

    @Test void recreatedTrackerRecoversPersistentPendingOrderWithoutSubmittingAgain() throws Exception {
        AiAdviceTrack t=demo("PENDING"); t.setEnteredAt(null);
        when(repository.findByStatusIn(anyList())).thenReturn(List.of(t));
        when(executor.orderDetail("ALTUSDT","entry-1")).thenReturn(
                new JSONObject().put("orderStatus","Filled").put("cumExecQty","1").put("avgPrice","100"));
        AiAdviceTracker restarted=new AiAdviceTracker(repository,bybit,mock(TelegramBotService.class),executor,configs);
        restarted.settle();
        assertThat(t.getStatus()).isEqualTo("TRACKING");
        verify(executor,never()).placeEntry(anyString(),anyString(),anyDouble(),anyDouble(),anyDouble(),anyDouble(),anyInt());
        verify(executor).setTradingStop("ALTUSDT","BUY",110,95);
    }

    @Test void minimumQuantityMustNotIncreaseRiskAboveRequestedBudget() {
        DemoOrderExecutor smallBudget = new DemoOrderExecutor(bybit) {
            @Override public Instrument instrument(String symbol) { return new Instrument(1,1,1,100,0.1); }
            @Override public double equityUsd() { return 10; }
        };
        assertThatThrownBy(() -> smallBudget.placeEntry("ALTUSDT","BUY",100,110,95,5,10))
                .isInstanceOf(IllegalStateException.class);
        verifyNoInteractions(bybit);
    }

    @Test void invalidAiGeometryMustBeRejectedBeforeAnyAccountRequest() {
        DemoOrderExecutor realExecutor = new DemoOrderExecutor(bybit);
        assertThatThrownBy(() -> realExecutor.placeEntry("ALTUSDT","BUY",100,95,110,5,10))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> realExecutor.placeEntry("ALTUSDT","BUY",100,Double.POSITIVE_INFINITY,95,5,10))
                .isInstanceOf(IllegalArgumentException.class);
        verifyNoInteractions(bybit);
    }
}
