package net.omaima.services;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import net.omaima.entities.FavoriteCompany;
import net.omaima.entities.User;
import net.omaima.repositories.FavoriteCompanyRepository;
import net.omaima.repositories.UserRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.time.LocalDateTime;
import java.util.List;
@Service
@Slf4j
@RequiredArgsConstructor
public class FavoriteCompanyService {

    private final FavoriteCompanyRepository favoriteRepository;
    private final UserRepository userRepository;

    @Transactional
    public FavoriteCompany addFavorite(Long userId, String ticker, String companyName) {
        log.info("Adding favorite for user {} : {}", userId, ticker);

        var existing = favoriteRepository.findByUserIdAndTicker(userId, ticker);
        if (existing.isPresent()) {
            log.warn("Already in favorites");
            return existing.get();
        }

        User user = userRepository.findById(userId)
                .orElseThrow(() -> new RuntimeException("User not found"));

        FavoriteCompany favorite = new FavoriteCompany();
        favorite.setUser(user);
        favorite.setTicker(ticker);
        favorite.setCompanyName(companyName);
        favorite.setAddedAt(LocalDateTime.now());

        return favoriteRepository.save(favorite);
    }

    @Transactional
    public void removeFavorite(Long userId, String ticker) {
        log.info("Removing favorite for user {} : {}", userId, ticker);
        favoriteRepository.findByUserIdAndTicker(userId, ticker)
                .ifPresent(favoriteRepository::delete);
    }

    public List<FavoriteCompany> getUserFavorites(Long userId) {
        return favoriteRepository.findByUserIdOrderByAddedAtDesc(userId);
    }

    public boolean isFavorite(Long userId, String ticker) {
        return favoriteRepository.findByUserIdAndTicker(userId, ticker).isPresent();
    }
}
