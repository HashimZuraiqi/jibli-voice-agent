# careem-mcp/

Careem MCP client for the groceries journey:

1. `search_groceries_get_top_user_items` / `search_groceries_items`
2. `create_grocery_cart_with_quantities`
3. `cart_get_basket_price`
4. confirm gate (in backend/)
5. `cart_grocery_checkout`

Always pass lat/lng; never blindly retry checkout or cart changes. Owner: Hashim.
