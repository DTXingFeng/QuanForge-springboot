package xyz.xingfeng.QuanForge.service;

import org.springframework.stereotype.Service;
import xyz.xingfeng.QuanForge.client.BybitGetClient;
import xyz.xingfeng.QuanForge.client.BybitMode;
import xyz.xingfeng.QuanForge.entity.ApiCredential;
import xyz.xingfeng.QuanForge.exception.NotFoundException;
import java.util.Map;

/** Exactly one saved credential and one explicitly pinned environment; signed read-only GET only. */
@Service
public class CredentialValidationService {
    private final ApiCredentialService credentials;
    private final BybitGetClient client;
    private final CredentialHealthRegistry health;
    public CredentialValidationService(ApiCredentialService credentials,BybitGetClient client,CredentialHealthRegistry health) {
        this.credentials=credentials;this.client=client;this.health=health;
    }
    private ApiCredential credential(long id) {
        return credentials.findById(id).orElseThrow(()->new NotFoundException("凭证不存在"));
    }
    public CredentialHealthRegistry.Health current(long id,BybitMode mode) {
        var c=credential(id);return health.current(c.getApiKey(),c.getApiSecret(),mode);
    }
    public CredentialHealthRegistry.Health validate(long id,BybitMode mode) {
        var c=credential(id);
        health.beginValidation(c.getApiKey(),c.getApiSecret(),mode);
        try {
            var info=client.probeKeyInformation(mode,c.getApiKey(),c.getApiSecret());
            if(info!=null) {
                var checked=health.observe(c.getApiKey(),c.getApiSecret(),mode,info.httpStatus(),info.body());
                if(info.httpStatus()!=404 && !Integer.valueOf(10017).equals(checked.retCode()))return checked;
            }
            var response=client.probeCredentials(mode,c.getApiKey(),c.getApiSecret());
            return health.observe(c.getApiKey(),c.getApiSecret(),mode,response.httpStatus(),response.body());
        } catch(Exception ignored) {
            return health.networkFailure(c.getApiKey(),c.getApiSecret(),mode);
        }
    }
}
