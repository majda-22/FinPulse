package net.omaima.controller;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import net.omaima.entities.FavoriteCompany;
import net.omaima.entities.User;
import net.omaima.services.FavoriteCompanyService;
import net.omaima.services.JwtTokenProvider;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import java.time.LocalDateTime;
import java.util.List;

@RestController
@RequestMapping("/api/v2/favorites")
@RequiredArgsConstructor
@Slf4j
public class FavoritesController {

    private final FavoriteCompanyService favoriteService;
    private final JwtTokenProvider jwtTokenProvider;

    record AddFavoriteRequest(String ticker, String companyName) {}
    record FavoriteResponse(Long id, String ticker, String companyName, String message) {}
    record FavoriteDTO(Long id, String ticker, String companyName, LocalDateTime addedAt) {}

    @PostMapping
    public ResponseEntity<FavoriteResponse> addFavorite(
            @RequestHeader("Authorization") String authHeader,
            @RequestBody AddFavoriteRequest request) {

        log.info("Adding favorite: ticker={}", request.ticker());

        try {
            String token = authHeader.replace("Bearer ", "");
            User user = jwtTokenProvider.getUserFromToken(token);

            FavoriteCompany favorite = favoriteService.addFavorite(
                    user.getId(), request.ticker(), request.companyName());

            return ResponseEntity.ok(new FavoriteResponse(
                    favorite.getId(), favorite.getTicker(),
                    favorite.getCompanyName(), "Ajouté aux favoris"));

        } catch (Exception e) {
            log.error("Error adding favorite", e);
            return ResponseEntity.internalServerError()
                    .body(new FavoriteResponse(null, null, null, e.getMessage()));
        }
    }

    @DeleteMapping("/{ticker}")
    public ResponseEntity<String> removeFavorite(
            @RequestHeader("Authorization") String authHeader,
            @PathVariable String ticker) {

        log.info("Removing favorite: ticker={}", ticker);

        try {
            String token = authHeader.replace("Bearer ", "");
            User user = jwtTokenProvider.getUserFromToken(token);

            favoriteService.removeFavorite(user.getId(), ticker);
            return ResponseEntity.ok("Retiré des favoris");

        } catch (Exception e) {
            log.error("Error removing favorite", e);
            return ResponseEntity.internalServerError().build();
        }
    }

    @GetMapping
    public ResponseEntity<List<FavoriteDTO>> getFavorites(
            @RequestHeader("Authorization") String authHeader) {

        try {
            String token = authHeader.replace("Bearer ", "");
            User user = jwtTokenProvider.getUserFromToken(token);

            List<FavoriteCompany> favorites = favoriteService.getUserFavorites(user.getId());
            List<FavoriteDTO> dtos = favorites.stream()
                    .map(f -> new FavoriteDTO(f.getId(), f.getTicker(),
                            f.getCompanyName(), f.getAddedAt()))
                    .toList();

            return ResponseEntity.ok(dtos);

        } catch (Exception e) {
            log.error("Error fetching favorites", e);
            return ResponseEntity.internalServerError().build();
        }
    }

    @GetMapping("/{ticker}")
    public ResponseEntity<Boolean> isFavorite(
            @RequestHeader("Authorization") String authHeader,
            @PathVariable String ticker) {

        try {
            String token = authHeader.replace("Bearer ", "");
            User user = jwtTokenProvider.getUserFromToken(token);

            boolean isFavorite = favoriteService.isFavorite(user.getId(), ticker);
            return ResponseEntity.ok(isFavorite);

        } catch (Exception e) {
            log.error("Error checking favorite", e);
            return ResponseEntity.internalServerError().build();
        }
    }
}