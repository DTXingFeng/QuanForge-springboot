package xyz.xingfeng.QuanForge.service;

import org.json.JSONObject;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.autoconfigure.EnableAutoConfiguration;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.context.annotation.Configuration;
import org.springframework.boot.persistence.autoconfigure.EntityScan;
import org.springframework.data.jpa.repository.config.EnableJpaRepositories;
import org.springframework.test.util.ReflectionTestUtils;
import xyz.xingfeng.QuanForge.entity.*;
import xyz.xingfeng.QuanForge.repository.AiAdviceTrackRepository;

import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.*;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/** Real file SQLite and JPA, fake exchange. Child JVM has no application component scan or network clients. */
class DurableEntryTests {
    @TempDir Path temp;
    static final List<String> ACTIVE=List.of("PENDING","TRACKING");

    @Configuration(proxyBeanMethods=false)
    @EnableAutoConfiguration
    @EntityScan(basePackageClasses=AiAdviceTrack.class)
    @EnableJpaRepositories(basePackageClasses=AiAdviceTrackRepository.class)
    static class DatabaseOnly {}

    static ConfigurableApplicationContext open(Path db) {
        return new SpringApplicationBuilder(DatabaseOnly.class).web(WebApplicationType.NONE).run(
                "--spring.datasource.url=jdbc:sqlite:"+db.toAbsolutePath()+"?busy_timeout=5000",
                "--spring.jpa.hibernate.ddl-auto=update", "--spring.main.banner-mode=off",
                "--logging.level.root=ERROR");
    }

    static AiAdviceTracker tracker(AiAdviceTrackRepository repository, DemoOrderExecutor executor) {
        AiConfigService config=mock(AiConfigService.class);
        AiConfig cfg=new AiConfig(); cfg.setAutoOrderEnabled(true);
        when(config.getConfig()).thenReturn(cfg);
        return new AiAdviceTracker(repository,mock(BybitService.class),mock(TelegramBotService.class),executor,config);
    }

    static void signal(AiAdviceTracker tracker, String symbol) {
        AiAlert alert=new AiAlert(); alert.setSymbol(symbol);
        ReflectionTestUtils.setField(alert,"id",41L);
        tracker.track(alert,"BUY",100,95,110);
    }

    @Test void timeoutRetainsCommittedIntentAndRecoveryNeverResubmits() throws Exception {
        Path db=temp.resolve("timeout.db");
        String link;
        try(var context=open(db)) {
            var repository=context.getBean(AiAdviceTrackRepository.class);
            var exchange=mock(DemoOrderExecutor.class);
            when(exchange.placeEntry(anyString(),anyString(),anyDouble(),anyDouble(),anyDouble(),anyDouble(),anyInt(),anyString()))
                    .thenAnswer(call -> {
                        // A separate connection must see the COMMITTED intent while the request is in progress.
                        try(var connection=java.sql.DriverManager.getConnection("jdbc:sqlite:"+db);
                            var result=connection.createStatement().executeQuery("select order_link_id,exec_mode from ai_advice_track")) {
                            assertThat(result.next()).isTrue();
                            assertThat(result.getString(1)).isEqualTo(call.getArgument(7));
                            assertThat(result.getString(2)).isEqualTo("DEMO");
                        }
                        throw new IllegalStateException("accepted but lost response");
                    });
            signal(tracker(repository,exchange),"ALTUSDT");
            var intent=repository.findByStatusIn(ACTIVE).getFirst();
            link=intent.getOrderLinkId();
            assertThat(intent.getOrderId()).isNull();
            assertThat(intent.getDemoSlot()).isNotNull();
        }
        try(var context=open(db)) {
            var repository=context.getBean(AiAdviceTrackRepository.class);
            var exchange=mock(DemoOrderExecutor.class);
            when(exchange.orderDetailByLink("ALTUSDT",link)).thenReturn(new JSONObject()
                    .put("orderId","accepted-1").put("qty","1").put("orderStatus","Filled")
                    .put("cumExecQty","1").put("avgPrice","100"));
            var restarted=tracker(repository,exchange);
            signal(restarted,"OTHERUSDT"); // a different symbol must not bypass account reservation
            restarted.settle();
            var recovered=repository.findByStatusIn(ACTIVE).getFirst();
            assertThat(recovered.getOrderId()).isEqualTo("accepted-1");
            assertThat(recovered.getStatus()).isEqualTo("TRACKING");
            assertThat(recovered.getOrderLinkId()).isEqualTo(link);
            verify(exchange,never()).placeEntry(anyString(),anyString(),anyDouble(),anyDouble(),anyDouble(),anyDouble(),anyInt(),anyString());
            verify(exchange).setTradingStop("ALTUSDT","BUY",110,95);
        }
    }

    @Test void separateTrackersRaceForOneAccountOnlyOneCanSend() throws Exception {
        try(var context=open(temp.resolve("race.db"))) {
            var repository=context.getBean(AiAdviceTrackRepository.class);
            var exchange=mock(DemoOrderExecutor.class);
            when(exchange.placeEntry(anyString(),anyString(),anyDouble(),anyDouble(),anyDouble(),anyDouble(),anyInt(),anyString()))
                    .thenThrow(new IllegalStateException("timeout"));
            var one=tracker(repository,exchange); var two=tracker(repository,exchange);
            var start=new CountDownLatch(1);
            try(var pool=Executors.newFixedThreadPool(2)) {
                var tasks=List.of(pool.submit(() -> { start.await(); signal(one,"ALTUSDT"); return null;}),
                        pool.submit(() -> {start.await(); signal(two,"OTHERUSDT"); return null;}));
                start.countDown();
                for(var task:tasks) task.get(15,TimeUnit.SECONDS);
            }
            assertThat(repository.findByStatusIn(ACTIVE)).hasSize(1);
            verify(exchange,times(1)).placeEntry(anyString(),anyString(),anyDouble(),anyDouble(),anyDouble(),anyDouble(),anyInt(),anyString());
        }
    }

    @Test void lostAcknowledgementDatabaseWriteCanRecoverFromOriginalIntent() {
        try(var context=open(temp.resolve("ack-write.db"))) {
            var repository=context.getBean(AiAdviceTrackRepository.class);
            var writes=mock(AiAdviceTrackRepository.class,org.mockito.AdditionalAnswers.delegatesTo(repository));
            var count=new java.util.concurrent.atomic.AtomicInteger();
            doAnswer(call -> {
                if(count.incrementAndGet()==2) throw new org.springframework.dao.DataAccessResourceFailureException("disk failure after acceptance");
                return repository.saveAndFlush(call.getArgument(0));
            }).when(writes).saveAndFlush(any(AiAdviceTrack.class));
            var exchange=mock(DemoOrderExecutor.class);
            when(exchange.placeEntry(anyString(),anyString(),anyDouble(),anyDouble(),anyDouble(),anyDouble(),anyInt(),anyString()))
                    .thenReturn(new DemoOrderExecutor.Placement("accepted-2",1,1000));
            assertThatThrownBy(() -> signal(tracker(writes,exchange),"ALTUSDT"))
                    .isInstanceOf(org.springframework.dao.DataAccessException.class);
            var intent=repository.findByStatusIn(ACTIVE).getFirst();
            assertThat(intent.getOrderId()).isNull();
            when(exchange.orderDetailByLink("ALTUSDT",intent.getOrderLinkId())).thenReturn(new JSONObject()
                    .put("orderId","accepted-2").put("qty","1").put("orderStatus","Filled")
                    .put("cumExecQty","1").put("avgPrice","100"));
            tracker(repository,exchange).settle();
            assertThat(repository.findByStatusIn(ACTIVE).getFirst().getOrderId()).isEqualTo("accepted-2");
            verify(exchange,times(1)).placeEntry(anyString(),anyString(),anyDouble(),anyDouble(),anyDouble(),anyDouble(),anyInt(),anyString());
        }
    }

    @Test void abruptChildJvmExitAfterExchangeAcceptanceKeepsRecoverableIntent() throws Exception {
        Path db=temp.resolve("crash.db"), log=temp.resolve("child.log");
        String executable=Path.of(System.getProperty("java.home"),"bin","java").toString();
        var process=new ProcessBuilder(executable,"-cp",System.getProperty("java.class.path"),
                CrashProbe.class.getName(),db.toString()).redirectErrorStream(true).redirectOutput(log.toFile()).start();
        if(!process.waitFor(45,TimeUnit.SECONDS)) {process.destroyForcibly(); fail("Child JVM timeout");}
        assertThat(process.exitValue()).withFailMessage(java.nio.file.Files.readString(log)).isEqualTo(23);
        try(var context=open(db)) {
            var repository=context.getBean(AiAdviceTrackRepository.class);
            var intent=repository.findByStatusIn(ACTIVE).getFirst();
            assertThat(intent.getOrderLinkId()).isNotBlank();
            assertThat(intent.getOrderId()).isNull();
            var exchange=mock(DemoOrderExecutor.class);
            when(exchange.orderDetailByLink(anyString(),anyString())).thenThrow(new IllegalStateException("temporarily absent"));
            var restarted=tracker(repository,exchange);
            restarted.settle(); signal(restarted,"OTHERUSDT");
            assertThat(repository.findByStatusIn(ACTIVE)).hasSize(1);
            verify(exchange,never()).placeEntry(anyString(),anyString(),anyDouble(),anyDouble(),anyDouble(),anyDouble(),anyInt(),anyString());
        }
    }

    public static class CrashProbe {
        public static void main(String[] args) {
            var context=open(Path.of(args[0]));
            var exchange=mock(DemoOrderExecutor.class);
            when(exchange.placeEntry(anyString(),anyString(),anyDouble(),anyDouble(),anyDouble(),anyDouble(),anyInt(),anyString()))
                    .thenAnswer(call -> {Runtime.getRuntime().halt(23); return null;});
            signal(tracker(context.getBean(AiAdviceTrackRepository.class),exchange),"ALTUSDT");
            throw new AssertionError("Did not reach simulated acceptance");
        }
    }
}
