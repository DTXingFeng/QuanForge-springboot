package xyz.xingfeng.QuanForge;

/**
 * 研判体系版本：每次改变建议生成逻辑（提示词/模型/触发器/跟踪规则）时递增。
 * 纸面跟踪建仓时打上当前版本戳，复盘按版本分组——避免跨版本样本互相污染
 * （例：旧体系开的仓在新体系时代结算，按结算时间分组会记错账）。
 * <ul>
 *   <li>v1: 裸 LLM（四代提示词混跑，无模型参与）</li>
 *   <li>v2: LLM × 单域模型（仅 BTC/ETH/SOL 有效）</li>
 *   <li>v3: LLM × 双域模型路由（majors/alts 各自校准）</li>
 *   <li>v3.1: 模型预测升级为 BUY/SELL 前必调项，detail 必须写明共振/分歧；CYS 移出观察列表</li>
 * </ul>
 */
public final class SystemVersion {

	private SystemVersion() {
	}

	public static final String CURRENT = "v3.1-llm-dualmodel";
}
