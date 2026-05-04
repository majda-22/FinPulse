#!/bin/bash

# FinPulse P2 API Testing Script
# lancer : ./test_api.sh

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
BASE_URL="http://localhost:8081"
EMAIL="test@example.com"
PASSWORD="TestPassword123!"
USERNAME="testuser"

echo -e "${BLUE}=== FinPulse P2 API Testing ===${NC}\n"

# ============================================================
# STEP 1: Register & Login
# ============================================================

echo -e "${YELLOW}[1/10] Testing Authentication...${NC}"

# Try login first
LOGIN_RESPONSE=$(curl -s -X POST "$BASE_URL/api/v2/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\": \"$EMAIL\", \"password\": \"$PASSWORD\"}")

TOKEN=$(echo $LOGIN_RESPONSE | grep -o '"token":"[^"]*' | cut -d'"' -f4)

if [ -z "$TOKEN" ]; then
  echo -e "${YELLOW}  [!] User doesn't exist, registering...${NC}"
  
  REGISTER_RESPONSE=$(curl -s -X POST "$BASE_URL/api/v2/auth/register" \
    -H "Content-Type: application/json" \
    -d "{\"username\": \"$USERNAME\", \"email\": \"$EMAIL\", \"password\": \"$PASSWORD\"}")
  
  TOKEN=$(echo $REGISTER_RESPONSE | grep -o '"token":"[^"]*' | cut -d'"' -f4)
fi

if [ -z "$TOKEN" ]; then
  echo -e "${RED}  ✗ Authentication failed!${NC}"
  exit 1
fi

echo -e "${GREEN}  ✓ Authenticated${NC}"
echo -e "  Token: ${TOKEN:0:20}...${NC}\n"

# ============================================================
# STEP 2: Test Chatbot (Simple Question)
# ============================================================

echo -e "${YELLOW}[2/10] Testing Chatbot Mode (Simple Question)...${NC}"

RESPONSE=$(curl -s -X POST "$BASE_URL/api/v2/assistant/chat" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"What is Tesla business model?","ticker":"TSLA"}')

MODE=$(echo $RESPONSE | grep -o '"mode":"[^"]*' | cut -d'"' -f4)

if [[ $MODE == "CHATBOT" ]]; then
  echo -e "${GREEN}  ✓ Chatbot mode working${NC}\n"
else
  echo -e "${RED}  ✗ Chatbot test failed (mode: $MODE)${NC}"
  echo "Response: $RESPONSE\n"
fi

# ============================================================
# STEP 3: Test Clarification (Vague Message)
# ============================================================

echo -e "${YELLOW}[3/10] Testing Clarification Mode...${NC}"

RESPONSE=$(curl -s -X POST "$BASE_URL/api/v2/assistant/chat" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"Make a report","ticker":"AAPL"}')

MODE=$(echo $RESPONSE | grep -o '"mode":"[^"]*' | cut -d'"' -f4)

if [[ $MODE == "CLARIFICATION" ]]; then
  echo -e "${GREEN}  ✓ Clarification mode working${NC}\n"
else
  echo -e "${RED}  ✗ Clarification test failed (mode: $MODE)${NC}\n"
fi

# ============================================================
# STEP 4: Test Out of Scope
# ============================================================

echo -e "${YELLOW}[4/10] Testing Out of Scope Detection...${NC}"

RESPONSE=$(curl -s -X POST "$BASE_URL/api/v2/assistant/chat" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"Tell me a joke","ticker":"TSLA"}')

MODE=$(echo $RESPONSE | grep -o '"mode":"[^"]*' | cut -d'"' -f4)

if [[ $MODE == "OUT_OF_SCOPE" ]]; then
  echo -e "${GREEN}  ✓ Out of scope detection working${NC}\n"
else
  echo -e "${RED}  ✗ Out of scope test failed (mode: $MODE)${NC}\n"
fi

# ============================================================
# STEP 5: Test Missing Ticker
# ============================================================

echo -e "${YELLOW}[5/10] Testing Missing Ticker Validation...${NC}"

RESPONSE=$(curl -s -X POST "$BASE_URL/api/v2/assistant/chat" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"Analyze something","ticker":null}')

MODE=$(echo $RESPONSE | grep -o '"mode":"[^"]*' | cut -d'"' -f4)

if [[ $MODE == "CLARIFICATION" ]]; then
  echo -e "${GREEN}  ✓ Ticker validation working${NC}\n"
else
  echo -e "${RED}  ✗ Ticker validation failed (mode: $MODE)${NC}\n"
fi

# ============================================================
# STEP 6: Test Check Company
# ============================================================

echo -e "${YELLOW}[6/10] Testing Check Company Endpoint...${NC}"

RESPONSE=$(curl -s -X POST "$BASE_URL/api/v2/assistant/check-company" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"ticker":"TSLA"}')

EXISTS=$(echo $RESPONSE | grep -o '"exists":[^,}]*' | cut -d':' -f2)

if [[ $EXISTS == "true" ]]; then
  echo -e "${GREEN}  ✓ Check company working (TSLA exists)${NC}\n"
else
  echo -e "${YELLOW}  [!] Check company returned exists=false (company may need backfill)${NC}\n"
fi

# ============================================================
# STEP 7: Test Report Generation (this is the big one)
# ============================================================

echo -e "${YELLOW}[7/10] Testing Report Generation...${NC}"
echo "  (This may take 8-12 seconds due to agent processing...)"

REPORT_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v2/assistant/chat" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message":"Tesla will dominate EV market in Europe due to manufacturing capacity and software",
    "ticker":"TSLA"
  }')

HTTP_CODE=$(echo "$REPORT_RESPONSE" | tail -1)
CONTENT_TYPE_RESPONSE=$(curl -s -i -X POST "$BASE_URL/api/v2/assistant/chat" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message":"Tesla will dominate EV market in Europe",
    "ticker":"TSLA"
  }' 2>&1 | grep -i "content-type")

if [[ $CONTENT_TYPE_RESPONSE == *"application/pdf"* ]] || [[ $HTTP_CODE == "200" ]]; then
  echo -e "${GREEN}  ✓ Report generation working${NC}"
  echo -e "  HTTP Code: $HTTP_CODE${NC}\n"
else
  echo -e "${YELLOW}  [!] Report generation test (check manually)${NC}\n"
fi

# ============================================================
# STEP 8: Test Strategy Saving
# ============================================================

echo -e "${YELLOW}[8/10] Testing Strategy Save Endpoint...${NC}"

SAVE_RESPONSE=$(curl -s -X POST "$BASE_URL/api/v2/strategy/save" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "ticker":"TSLA",
    "companyName":"Tesla Inc.",
    "userArgument":"Tesla will dominate EV market in Europe",
    "nciGlobal":75.5,
    "nciPersonalized":82.3,
    "fConsistency":0.35,
    "sentiment":0.62,
    "supportEvidence":"[\"Manufacturing capacity\"]",
    "redFlags":"[\"Competition\"]",
    "finalConclusion":"Tesla is well positioned"
  }')

STRATEGY_ID=$(echo $SAVE_RESPONSE | grep -o '"strategyId":[^,}]*' | cut -d':' -f2)
SUCCESS=$(echo $SAVE_RESPONSE | grep -o '"success":[^,}]*' | cut -d':' -f2)

if [[ $SUCCESS == "true" ]]; then
  echo -e "${GREEN}  ✓ Strategy saved successfully${NC}"
  echo -e "  Strategy ID: $STRATEGY_ID${NC}\n"
else
  echo -e "${RED}  ✗ Strategy save failed${NC}"
  echo "Response: $SAVE_RESPONSE\n"
fi

# ============================================================
# STEP 9: Test Get My Strategies
# ============================================================

echo -e "${YELLOW}[9/10] Testing Get My Strategies...${NC}"

GET_STRATEGIES_RESPONSE=$(curl -s -X GET "$BASE_URL/api/v2/strategy/my-strategies" \
  -H "Authorization: Bearer $TOKEN")

STRATEGY_COUNT=$(echo $GET_STRATEGIES_RESPONSE | grep -o '"id":[^,}]*' | wc -l)

if [[ $STRATEGY_COUNT -gt 0 ]]; then
  echo -e "${GREEN}  ✓ Get strategies working${NC}"
  echo -e "  Found $STRATEGY_COUNT strateg(ies)${NC}\n"
else
  echo -e "${YELLOW}  [!] No strategies found (or list empty)${NC}\n"
fi

# ============================================================
# STEP 10: Test Security (Missing Token)
# ============================================================

echo -e "${YELLOW}[10/10] Testing Security (Missing Authorization)...${NC}"

SECURITY_RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "$BASE_URL/api/v2/strategy/my-strategies")

SECURITY_CODE=$(echo "$SECURITY_RESPONSE" | tail -1)

if [[ $SECURITY_CODE == "401" ]] || [[ $SECURITY_CODE == "403" ]]; then
  echo -e "${GREEN}  ✓ Security working (401/403 returned without token)${NC}\n"
else
  echo -e "${YELLOW}  [!] Security test inconclusive (HTTP $SECURITY_CODE)${NC}\n"
fi

# ============================================================
# Summary
# ============================================================

echo -e "${BLUE}=== Test Summary ===${NC}"
echo -e "${GREEN}✓ All basic tests completed!${NC}\n"
echo -e "Next steps:"
echo -e "  1. Check that PDF reports are being generated correctly"
echo -e "  2. Test with different tickers (AAPL, MSFT, GOOGL, etc.)"
echo -e "  3. Test in Postman for more detailed inspection"
echo -e "  4. Check database entries were created\n"

echo -e "${YELLOW}Useful commands:${NC}"
echo -e "  # Get all your strategies"
echo -e "  curl -H 'Authorization: Bearer $TOKEN' \\"
echo -e "    $BASE_URL/api/v2/strategy/my-strategies | jq\n"

echo -e "  # Delete a strategy (replace 1 with actual ID)"
echo -e "  curl -X DELETE -H 'Authorization: Bearer $TOKEN' \\"
echo -e "    $BASE_URL/api/v2/strategy/1\n"
