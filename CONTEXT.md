# Mini E-Commerce

A small storefront for digital goods. Shoppers browse a catalogue, read product detail, and assemble a cart through to a mock checkout.

## Language

**Product**:
A digital good offered for sale — an e-book, a software licence, or an online course.

**Category**:
The kind of digital good a Product is. Every Product has exactly one.

**Review**:
A shopper's written verdict on a Product.

**Shopper**:
An anonymous visitor browsing the storefront. Recognised across requests without ever identifying themselves, and owner of exactly one Cart.
_Avoid_: User, customer, guest

**Cart**:
The set of Products a Shopper intends to buy, held on the server and read by the browser.
_Avoid_: Basket, order

**Line Item**:
One Product within a Cart, together with the quantity wanted of it.
_Avoid_: Cart product, cart entry

**Checkout**:
The mock act of converting a Cart into a completed purchase. Nothing is charged and no order is stored.
