package xyz.xingfeng.QuanForge.service;

import okhttp3.Request;
import okhttp3.Response;
import org.json.JSONArray;
import org.json.JSONObject;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import xyz.xingfeng.QuanForge.client.ProxiedHttpClients;

import java.io.InputStream;
import java.net.URL;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 加快讯聚合服务（HTX 式快讯流的后端）：
 * 定时拉取四个公开源，合并去重后按时间倒序提供。
 * <ul>
 *   <li>华尔街见闻快讯（中文，实时密度高）</li>
 *   <li>Binance 公告（新币上线/下架等，直接影响币价）</li>
 *   <li>CoinDesk RSS（英文加密专业媒体）</li>
 *   <li>Cointelegraph RSS（英文加密媒体）</li>
 * </ul>
 * 单源故障自动降级，不影响其余源。请求遵循代理配置。
 */
@Service
public class NewsService {

	private static final Logger log = LoggerFactory.getLogger(NewsService.class);

	/** 快讯项（不可变） */
	public record NewsItem(String source, String title, String content, String url,
			long publishedAt) {
	}

	/** 内存缓存上限（条） */
	private static final int MAX_ITEMS = 300;

	/** 前端展示的内容截断长度 */
	private static final int CONTENT_MAX = 280;

	private final ProxiedHttpClients clients;

	/** 以 URL 为键的快讯缓存 */
	private final Map<String, NewsItem> cache = new ConcurrentHashMap<>();

	/** 最近一次成功刷新时间（epoch millis） */
	private volatile long lastRefreshAt = 0;

	public NewsService(ProxiedHttpClients clients) {
		this.clients = clients;
	}

	/** 每 60 秒拉取一轮所有源（启动 5 秒后先拉一次） */
	@Scheduled(fixedDelay = 60_000, initialDelay = 5_000)
	public void refresh() {
		List<NewsItem> merged = new ArrayList<>();
		merged.addAll(safeFetch("华尔街见闻", this::fetchWscn));
		merged.addAll(safeFetch("Binance公告", this::fetchBinance));
		merged.addAll(safeFetch("CoinDesk", this::fetchCoinDesk));
		merged.addAll(safeFetch("Cointelegraph", this::fetchCointelegraph));
		if (merged.isEmpty()) {
			log.warn("本轮快讯拉取全部失败，保留旧缓存（{} 条）", cache.size());
			return;
		}
		for (NewsItem item : merged) {
			cache.put(item.url(), item);
		}
		trim();
		lastRefreshAt = System.currentTimeMillis();
	}

	/** 最新快讯（时间倒序），可按源过滤 */
	public List<NewsItem> latest(int limit, String source) {
		List<NewsItem> list = new ArrayList<>(cache.values());
		if (source != null && !source.isBlank() && !"all".equalsIgnoreCase(source)) {
			list.removeIf(i -> !i.source().equalsIgnoreCase(source));
		}
		list.sort(Comparator.comparingLong(NewsItem::publishedAt).reversed());
		return list.size() > limit ? list.subList(0, limit) : list;
	}

	public long getLastRefreshAt() {
		return lastRefreshAt;
	}

	// ==================== 各源解析 ====================

	/** 华尔街见闻：全球频道快讯（JSON） */
	private List<NewsItem> fetchWscn() throws Exception {
		String body = httpGet("https://api-one-wscn.awtmt.com/apiv1/content/lives"
				+ "?channel=global-channel&limit=30&accept=live%2Cvip-live");
		JSONObject json = new JSONObject(body);
		JSONArray items = json.getJSONObject("data").getJSONArray("items");
		List<NewsItem> out = new ArrayList<>();
		for (int i = 0; i < items.length(); i++) {
			JSONObject it = items.getJSONObject(i);
			String title = optTrim(it, "title");
			String content = optTrim(it, "content_text");
			if (content.isEmpty()) {
				content = optTrim(it, "content");
			}
			if (title.isEmpty() && content.isEmpty()) {
				continue;
			}
			long ts = it.optLong("display_time") * 1000;
			String uri = it.optString("uri", "");
			String url = uri.startsWith("http") ? uri
					: "https://wallstreetcn.com/live/global" + (uri.isEmpty() ? "" : "/" + uri);
			out.add(new NewsItem("华尔街见闻",
					title.isEmpty() ? truncate(content, 60) : title,
					truncate(content, CONTENT_MAX), url, ts));
		}
		return out;
	}

	/** Binance 公告：新币/上线/下架目录（JSON） */
	private List<NewsItem> fetchBinance() throws Exception {
		String body = httpGet("https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
				+ "?type=1&pageNo=1&pageSize=20&catalogId=48");
		JSONObject json = new JSONObject(body);
		JSONArray catalogs = json.getJSONObject("data").getJSONArray("catalogs");
		List<NewsItem> out = new ArrayList<>();
		for (int c = 0; c < catalogs.length(); c++) {
			JSONArray articles = catalogs.getJSONObject(c).optJSONArray("articles");
			if (articles == null) {
				continue;
			}
			for (int i = 0; i < articles.length(); i++) {
				JSONObject a = articles.getJSONObject(i);
				String title = optTrim(a, "title");
				if (title.isEmpty()) {
					continue;
				}
				long ts = a.optLong("releaseDate");
				String code = a.optString("code", "");
				out.add(new NewsItem("Binance", title, truncate(title, CONTENT_MAX),
						"https://www.binance.com/en/support/announcement/" + code, ts));
			}
		}
		return out;
	}

	/** CoinDesk RSS（XML） */
	private List<NewsItem> fetchCoinDesk() throws Exception {
		return fetchRss("CoinDesk",
				"https://www.coindesk.com/arc/outboundfeeds/rss/");
	}

	/** Cointelegraph RSS（XML） */
	private List<NewsItem> fetchCointelegraph() throws Exception {
		return fetchRss("Cointelegraph", "https://cointelegraph.com/rss");
	}

	// ==================== 工具 ====================

	private List<NewsItem> fetchRss(String source, String feedUrl) throws Exception {
		try (Response response = clients.obtain().newCall(
				new Request.Builder().url(feedUrl)
						.header("User-Agent", "Mozilla/5.0 QuanForge/1.0")
						.get().build()).execute()) {
			if (!response.isSuccessful() || response.body() == null) {
				throw new IllegalStateException("HTTP " + response.code());
			}
			return parseRss(source, response.body().byteStream());
		}
	}

	/** 极简 RSS 2.0 解析（ javax.xml DOM，仅取 title/link/pubDate/description） */
	private List<NewsItem> parseRss(String source, InputStream in) throws Exception {
		var factory = javax.xml.parsers.DocumentBuilderFactory.newInstance();
		// 防御 XXE：禁外部实体
		factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
		factory.setNamespaceAware(false);
		var doc = factory.newDocumentBuilder().parse(in);
		var nodes = doc.getElementsByTagName("item");
		SimpleDateFormat fmt = new SimpleDateFormat("EEE, dd MMM yyyy HH:mm:ss zzz", Locale.ENGLISH);
		List<NewsItem> out = new ArrayList<>();
		for (int i = 0; i < nodes.getLength(); i++) {
			var item = nodes.item(i);
			String title = firstChildText(item, "title");
			String link = firstChildText(item, "link");
			String desc = stripHtml(firstChildText(item, "description"));
			String pub = firstChildText(item, "pubDate");
			if (title.isEmpty() || link.isEmpty()) {
				continue;
			}
			long ts = 0;
			try {
				Date d = fmt.parse(pub);
				if (d != null) {
					ts = d.getTime();
				}
			} catch (Exception ignore) {
				// 时间解析失败按 0 处理，排序沉底但不丢条目
			}
			out.add(new NewsItem(source, title, truncate(desc, CONTENT_MAX), link, ts));
		}
		return out;
	}

	private String firstChildText(org.w3c.dom.Node parent, String tag) {
		var list = ((org.w3c.dom.Element) parent).getElementsByTagName(tag);
		if (list.getLength() == 0) {
			return "";
		}
		String text = list.item(0).getTextContent();
		return text == null ? "" : text.trim();
	}

	private String httpGet(String url) throws Exception {
		try (Response response = clients.obtain().newCall(
				new Request.Builder().url(url)
						.header("User-Agent", "Mozilla/5.0 QuanForge/1.0")
						.get().build()).execute()) {
			if (!response.isSuccessful() || response.body() == null) {
				throw new IllegalStateException("HTTP " + response.code());
			}
			return response.body().string();
		}
	}

	/** 单源拉取兜底：失败记日志返回空列表，不拖垮整轮 */
	private List<NewsItem> safeFetch(String name,
			java.util.concurrent.Callable<List<NewsItem>> fetcher) {
		try {
			List<NewsItem> items = fetcher.call();
			log.debug("快讯源 {} 拉取 {} 条", name, items.size());
			return items;
		} catch (Exception e) {
			log.warn("快讯源 {} 拉取失败: {}", name, e.getMessage());
			return Collections.emptyList();
		}
	}

	private String optTrim(JSONObject obj, String key) {
		String v = obj.optString(key, "");
		return v == null ? "" : v.trim();
	}

	private String truncate(String s, int max) {
		if (s == null) {
			return "";
		}
		return s.length() <= max ? s : s.substring(0, max) + "…";
	}

	private String stripHtml(String s) {
		if (s == null) {
			return "";
		}
		return s.replaceAll("<[^>]+>", "").trim();
	}

	/** 缓存裁剪：只保留最新 MAX_ITEMS 条 */
	private void trim() {
		if (cache.size() <= MAX_ITEMS) {
			return;
		}
		List<NewsItem> sorted = latest(MAX_ITEMS, "all");
		var keep = new java.util.HashSet<String>();
		sorted.forEach(i -> keep.add(i.url()));
		cache.keySet().retainAll(keep);
	}
}
