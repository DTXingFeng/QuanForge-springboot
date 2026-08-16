package xyz.xingfeng.QuanForge.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.IdClass;
import jakarta.persistence.Table;

import java.io.Serializable;
import java.time.LocalDateTime;

/**
 * 1 分钟 K 线历史库（模型训练数据源）。
 * 复合主键 (symbol, openTime)；由 KlineHistoryService 从 Bybit 批量拉取，
 * 只增不改——历史 K 线是 Immutable 事实。
 */
@Entity
@Table(name = "kline_1m")
@IdClass(Kline1m.Kline1mId.class)
public class Kline1m {

	/** 复合主键 */
	public record Kline1mId(String symbol, LocalDateTime openTime) implements Serializable {
	}

	@Id
	@Column(nullable = false, length = 32)
	private String symbol;

	@Id
	@Column(name = "open_time", nullable = false)
	private LocalDateTime openTime;

	@Column(nullable = false)
	private Double open;

	@Column(nullable = false)
	private Double high;

	@Column(nullable = false)
	private Double low;

	@Column(nullable = false)
	private Double close;

	@Column(nullable = false)
	private Double volume;

	@Column(nullable = false)
	private Double turnover;

	public Kline1m() {
	}

	public Kline1m(String symbol, LocalDateTime openTime, double open, double high,
			double low, double close, double volume, double turnover) {
		this.symbol = symbol;
		this.openTime = openTime;
		this.open = open;
		this.high = high;
		this.low = low;
		this.close = close;
		this.volume = volume;
		this.turnover = turnover;
	}

	public String getSymbol() {
		return symbol;
	}

	public LocalDateTime getOpenTime() {
		return openTime;
	}

	public Double getOpen() {
		return open;
	}

	public Double getHigh() {
		return high;
	}

	public Double getLow() {
		return low;
	}

	public Double getClose() {
		return close;
	}

	public Double getVolume() {
		return volume;
	}

	public Double getTurnover() {
		return turnover;
	}
}
