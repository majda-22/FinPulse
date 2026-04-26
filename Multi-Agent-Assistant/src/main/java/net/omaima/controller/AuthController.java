package net.omaima.controller;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import net.omaima.entities.User;
import net.omaima.services.JwtTokenProvider;
import net.omaima.services.UserService;
import org.springframework.http.ResponseEntity;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v2/auth")
@RequiredArgsConstructor
@Slf4j
public class AuthController {

    private final UserService userService;
    private final JwtTokenProvider jwtTokenProvider;
    private final PasswordEncoder passwordEncoder;

    record RegisterRequest(String username, String email, String password) {}
    record LoginRequest(String username, String password) {}
    record AuthResponse(String token, String message) {}
    record TokenValidationResponse(boolean valid, String username) {}

    @PostMapping("/register")
    public ResponseEntity<AuthResponse> register(@RequestBody RegisterRequest request) {
        log.info("Registration request: username={}", request.username());

        try {
            if (userService.userExists(request.username())) {
                return ResponseEntity.badRequest()
                        .body(new AuthResponse(null, "Utilisateur déjà existant"));
            }

            User user = userService.registerUser(request.username(), request.email(), request.password());
            String token = jwtTokenProvider.generateToken(user);

            log.info("User registered successfully: {}", user.getUsername());
            return ResponseEntity.ok(new AuthResponse(token, "Inscription réussie"));

        } catch (Exception e) {
            log.error("Registration error", e);
            return ResponseEntity.internalServerError()
                    .body(new AuthResponse(null, e.getMessage()));
        }
    }

    @PostMapping("/login")
    public ResponseEntity<AuthResponse> login(@RequestBody LoginRequest request) {
        log.info("Login request: username={}", request.username());

        try {
            User user = userService.findByUsername(request.username());

            if (user == null) {
                return ResponseEntity.badRequest()
                        .body(new AuthResponse(null, "Utilisateur non trouvé"));
            }

            if (!passwordEncoder.matches(request.password(), user.getPasswordHash())) {
                return ResponseEntity.badRequest()
                        .body(new AuthResponse(null, "Mot de passe incorrect"));
            }

            String token = jwtTokenProvider.generateToken(user);

            log.info("Login successful: {}", user.getUsername());
            return ResponseEntity.ok(new AuthResponse(token, "Connexion réussie"));

        } catch (Exception e) {
            log.error("Login error", e);
            return ResponseEntity.internalServerError()
                    .body(new AuthResponse(null, e.getMessage()));
        }
    }

    @PostMapping("/validate")
    public ResponseEntity<TokenValidationResponse> validateToken(
            @RequestHeader("Authorization") String authHeader) {

        try {
            String token = authHeader.replace("Bearer ", "");

            if (!jwtTokenProvider.validateToken(token)) {
                return ResponseEntity.badRequest()
                        .body(new TokenValidationResponse(false, "Token invalide"));
            }

            User user = jwtTokenProvider.getUserFromToken(token);
            return ResponseEntity.ok(new TokenValidationResponse(true, user.getUsername()));

        } catch (Exception e) {
            log.error("Token validation error", e);
            return ResponseEntity.badRequest()
                    .body(new TokenValidationResponse(false, e.getMessage()));
        }
    }
}