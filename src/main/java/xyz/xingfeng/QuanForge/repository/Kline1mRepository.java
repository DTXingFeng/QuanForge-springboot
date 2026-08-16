package xyz.xingfeng.QuanForge.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import xyz.xingfeng.QuanForge.entity.Kline1m;

import java.time.LocalDateTime;
import java.util.List;

public interface Kline1mRepository extends JpaRepository<Kline1m, Kline1m.Kline1mId> {

	long countBySymbol(String symbol);

	List<Kline1m> findBySymbolAndOpenTimeBetweenOrderByOpenTimeAsc(String symbol,
			LocalDateTime from, LocalDateTime to);

	@Query("select max(k.openTime) from Kline1m k where k.symbol = :symbol")
	LocalDateTime latestOpenTime(@Param("symbol") String symbol);

	List<Kline1m> findTop500BySymbolOrderByOpenTimeDesc(String symbol);
}
