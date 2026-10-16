# Schema

GitHub renders the diagram below. The grain statements under it matter more than
the picture: almost every wrong number in analytics comes from joining two
tables at different grains and not noticing the fan-out.

```mermaid
erDiagram
    CUSTOMERS  ||--o{ ORDERS      : places
    CUSTOMERS  ||--o{ SESSIONS    : browses
    ORDERS     ||--|{ ORDER_ITEMS : contains
    PRODUCTS   ||--o{ ORDER_ITEMS : "appears in"

    CUSTOMERS {
        bigint customer_id PK
        varchar email "inconsistent case in raw"
        date    signup_date
        varchar country "4.0% missing"
        varchar acquisition_channel
    }
    ORDERS {
        bigint    order_id PK
        bigint    customer_id FK "40 rows orphaned"
        varchar   order_ts "2 formats in raw"
        varchar   status "8 spellings, 5 states"
        varchar   channel
        varchar   discount_code "~72% null"
    }
    ORDER_ITEMS {
        bigint  order_item_id PK "717 duplicate rows in raw"
        bigint  order_id FK
        bigint  product_id FK
        integer quantity "negative = return"
        decimal unit_price "72 x100 typos"
    }
    PRODUCTS {
        bigint  product_id PK
        varchar product_name
        varchar category
        decimal unit_cost
        decimal list_price
    }
    SESSIONS {
        bigint  session_id PK
        bigint  customer_id FK
        date    session_date
        varchar device
        varchar source
        integer pages_viewed
        integer converted
    }
    MARKETING_SPEND {
        date    spend_month
        varchar channel
        decimal spend_ngn
    }
```

## Grain

| Table | One row per | Rows |
|---|---|---|
| `customers` | customer | 12,000 |
| `products` | product SKU | 72 |
| `orders` | order | 31,127 |
| `order_items` | line item within an order | 60,585 |
| `sessions` | browsing session | 104,449 |
| `marketing_spend` | channel × month | 96 |

`marketing_spend` has **no customer key**. It can only be joined on
`(channel, month)`, which is the reason the CAC figures in Q8 are blended rather
than causal. This is not a modelling oversight; it is what the data permits, and
saying so is the difference between an analyst and a dashboard.

## Model layers

```
raw_*            all VARCHAR, exactly as the CSV arrived
  └─ stg_*       cast, trimmed, de-duplicated, with quality flags
       ├─ fct_orders        one row per order, revenue rolled up from items
       ├─ analysis_orders   fct_orders filtered to recognised, non-test, non-orphan
       └─ dim_customers     one row per customer, lifetime aggregates
            └─ q1..q10      the analysis views
```

Filtering happens in exactly one place. `analysis_orders` is the only view the
analysis queries read, so no individual query can forget to exclude test
accounts and then quietly disagree with its neighbour. When two dashboards show
different revenue for the same month, this is almost always why.

## Join hazards in this schema

- **`orders` → `order_items` fans out.** Joining them and then summing an order
  level column multiplies it by the line count. `fct_orders` pre-aggregates
  items to order grain so downstream queries join at 1:1.
- **`customers` → `orders` is 1:many and 40 orders have no parent.** A plain
  `INNER JOIN` silently drops ₦300,000 of real revenue. `fct_orders` uses a
  `LEFT JOIN` and flags `is_orphan_order` instead.
- **`sessions` and `orders` share no key.** There is no session id on an order,
  so the funnel in Q9 is a same-day heuristic, not a tracked journey. Any
  statement of the form "this session caused this order" is unsupported.
