package xyz.xingfeng.QuanForge.service;

import org.json.JSONObject;
import org.springframework.stereotype.Component;
import xyz.xingfeng.QuanForge.client.BybitMode;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Clock;
import java.time.Instant;
import java.util.HexFormat;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/** In-memory, environment/credential-version scoped observations. Never stores or returns raw keys/errors. */
@Component
public class CredentialHealthRegistry {
    public record Health(String status, String level, String message, String environment,
                         Long checkedAt, Integer retCode, Integer httpStatus, boolean stale,
                         String expiresAt,Integer remainingDays,Boolean readOnly,Boolean tradePermissionConfigured) {}
    private record Metadata(String expiresAt,Integer days,Boolean readOnly,Boolean tradePermission) {}
    private final Map<String,Health> observations=new ConcurrentHashMap<>();
    private final Map<String,Metadata> metadata=new ConcurrentHashMap<>();
    private final Map<String,Long> validationAttempts=new ConcurrentHashMap<>();
    private final Clock clock;
    public CredentialHealthRegistry() { this(Clock.systemUTC()); }
    public CredentialHealthRegistry(Clock clock) { this.clock=clock; }
    public void beginValidation(String key,String secret,BybitMode mode) { validationAttempts.put(identity(key,secret,mode),clock.millis()); }

    private String identity(String key,String secret,BybitMode mode) {
        try {
            return mode.name()+HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(
                    ((key==null?"":key)+"\0"+(secret==null?"":secret)).getBytes(StandardCharsets.UTF_8)));
        } catch(java.security.NoSuchAlgorithmException impossible) {throw new IllegalStateException(impossible);}
    }

    public Health current(String key,String secret,BybitMode mode) {
        Health h=observations.get(identity(key,secret,mode));
        if(h==null) return new Health("NOT_CHECKED","warning","尚未检测；已保存不代表密钥有效",mode.name(),null,null,null,true,null,null,null,null);
        boolean stale=clock.millis()-h.checkedAt()>300000 || clock.millis()<h.checkedAt();
        Long validated=validationAttempts.get(identity(key,secret,mode));
        if(validated!=null)stale=stale || clock.millis()-validated>300000 || clock.millis()<validated;
        if(h.expiresAt()!=null && Instant.parse(h.expiresAt()).toEpochMilli()<=clock.millis())
            return new Health("EXPIRED","error","根据 Bybit 到期时间，密钥已过期，请更新凭证",mode.name(),h.checkedAt(),h.retCode(),h.httpStatus(),stale,h.expiresAt(),h.remainingDays(),h.readOnly(),h.tradePermissionConfigured());
        if(stale && (h.status().equals("VALID") || h.status().equals("READ_ONLY_OK") || h.status().equals("EXPIRING")))
            return new Health("STALE","warning","上次检测已超过5分钟，请重新检测",mode.name(),h.checkedAt(),h.retCode(),h.httpStatus(),true,h.expiresAt(),h.remainingDays(),h.readOnly(),h.tradePermissionConfigured());
        return new Health(h.status(),h.level(),h.message(),h.environment(),h.checkedAt(),h.retCode(),h.httpStatus(),stale,h.expiresAt(),h.remainingDays(),h.readOnly(),h.tradePermissionConfigured());
    }

    public Health networkFailure(String key,String secret,BybitMode mode) {
        return save(key,secret,mode,"NETWORK_ERROR","warning","未能连接 Bybit，请检查网络和代理；无法判断密钥是否有效",null,null);
    }

    public Health observe(String key,String secret,BybitMode mode,int http,String raw) {
        Integer code=null;
        boolean hasMetadata=false;
        try {
            JSONObject body=new JSONObject(raw);if(body.has("retCode"))code=body.getInt("retCode");
            JSONObject result=body.optJSONObject("result");
            if(code!=null && code==0 && http>=200 && http<300 && result!=null
                    && (result.has("expiredAt") || result.has("deadlineDay") || result.has("readOnly"))) {
                String expiry=null;
                try {Instant parsed=Instant.parse(result.optString("expiredAt"));if(parsed.isAfter(Instant.parse("2000-01-01T00:00:00Z")))expiry=parsed.toString();}
                catch(Exception ignored) {}
                Integer days=result.has("deadlineDay")&&!result.isNull("deadlineDay")?result.getInt("deadlineDay"):null;
                Boolean readOnly=result.has("readOnly")?result.getInt("readOnly")==1:null;
                Boolean trade=null;
                JSONObject permissions=result.optJSONObject("permissions");
                if(permissions!=null && readOnly!=null) {
                    String contract=permissions.optJSONArray("ContractTrade")==null?"":permissions.getJSONArray("ContractTrade").toString();
                    String derivatives=permissions.optJSONArray("Derivatives")==null?"":permissions.getJSONArray("Derivatives").toString();
                    trade=!readOnly && (contract.contains("\"Order\"") || derivatives.contains("\"DerivativesTrade\""));
                }
                metadata.put(identity(key,secret,mode),new Metadata(expiry,days,readOnly,trade));hasMetadata=true;
                beginValidation(key,secret,mode);
            }
        }
        catch(Exception ignored) { /* Untrusted upstream text is never returned or logged. */ }
        String status="API_ERROR",level="warning",message="Bybit 接口返回异常；本次未确认密钥有效性";
        if(code!=null) {
            switch(code) {
                case 33004,-2015 -> {status="EXPIRED";level="error";message="Bybit API 密钥已过期，请在对应环境重新生成并更新凭证";}
                case 10003 -> {status="INVALID_OR_ENVIRONMENT";level="error";message="密钥无效或环境不匹配；Demo 密钥需使用 Demo 环境";}
                case 10007 -> {status="AUTH_FAILED";level="error";message="Bybit 身份验证失败，请检查密钥与 Secret";}
                case 10005 -> {status="PERMISSION_DENIED";level="error";message="密钥权限不足，请检查所需只读/账户权限";}
                case 10010 -> {status="IP_RESTRICTED";level="error";message="当前服务器 IP 不在密钥白名单内";}
                case 10004 -> {status="SIGNATURE_ERROR";level="error";message="Bybit 签名校验失败，请检查 Secret 和签名配置";}
                case 10002,-1 -> {status="CLOCK_ERROR";message="请求时间超出窗口，请检查服务器时钟；不能据此判定密钥过期";}
                case 10006,429 -> {status="RATE_LIMITED";message="Bybit 请求限流，请稍后重试";}
                case 0 -> {if(http>=200 && http<300) {
                    Health old=observations.get(identity(key,secret,mode));
                    if(!hasMetadata && old!=null && old.status().equals("EXPIRED"))return current(key,secret,mode);
                    Metadata m=metadata.get(identity(key,secret,mode));
                    status="READ_ONLY_OK";message="只读鉴权成功；到期时间和交易能力尚未完整确认";
                    if(m!=null) {
                        if(m.expiresAt()!=null && Instant.parse(m.expiresAt()).toEpochMilli()<=clock.millis()) {
                            status="EXPIRED";level="error";message="根据 Bybit 到期时间，密钥已过期，请更新凭证";
                        } else if((m.expiresAt()!=null && Instant.parse(m.expiresAt()).toEpochMilli()-clock.millis()<=7*86400000L)
                                || (m.days()!=null && m.days()>=0 && m.days()<=7)) {
                            status="EXPIRING";message="密钥即将到期，请按精确到期时间提前更新；实际交易未验证";
                        } else if(Boolean.TRUE.equals(m.readOnly()) || Boolean.FALSE.equals(m.tradePermission())) {
                            status="PERMISSION_LIMITED";message="鉴权成功，但密钥未配置合约下单权限";
                        } else if(m.expiresAt()!=null) {
                            status="VALID";level="success";message="鉴权成功且到期时间未到；实际下单能力未验证";
                        }
                    }
                }}
                default -> {}
            }
        }
        if(status.equals("API_ERROR")) {
            if(http==401) {status="AUTH_FAILED";level="error";message="Bybit 拒绝鉴权，请检查密钥与环境";}
            else if(http==403) {status="FORBIDDEN";message="Bybit 拒绝访问，请检查 IP、地区或频率限制；不等同密钥过期";}
            else if(http==429) {status="RATE_LIMITED";message="Bybit 请求限流，请稍后重试";}
            else if(http>=500) {status="SERVER_ERROR";message="Bybit 服务暂不可用，无法验证密钥";}
            else if(code==null) {status="UNEXPECTED_RESPONSE";message="Bybit 响应格式异常，无法验证密钥";}
        }
        return save(key,secret,mode,status,level,message,code,http);
    }

    private Health save(String key,String secret,BybitMode mode,String status,String level,String message,Integer code,Integer http) {
        Metadata m=metadata.get(identity(key,secret,mode));
        Health h=new Health(status,level,message,mode.name(),clock.millis(),code,http,false,
                m==null?null:m.expiresAt(),m==null?null:m.days(),m==null?null:m.readOnly(),m==null?null:m.tradePermission());
        observations.put(identity(key,secret,mode),h);return h;
    }
}
