package xyz.xingfeng.QuanForge.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import xyz.xingfeng.QuanForge.entity.AiAdviceTrack;

import java.util.Collection;
import java.util.List;

public interface AiAdviceTrackRepository extends JpaRepository<AiAdviceTrack, Long> {

	List<AiAdviceTrack> findByStatusIn(Collection<String> statuses);

	List<AiAdviceTrack> findBySymbolAndStatusIn(String symbol, Collection<String> statuses);

	List<AiAdviceTrack> findTop50ByOrderByCreatedAtDesc();
}
