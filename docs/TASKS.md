Vue.js + PYTHON (Backend) Home Assignment: Full Stack Developer
Duration: ~3 hours
SCENARIO
Build a small full-stack application for a mini e-commerce platform. The platform sells a limited range of digital products (e.g., e-books, software licenses, and online courses). Users should be able to browse products, view product details, and manage a shopping cart.
Pages to Implement
1. PRODUCT LIST PAGE
PURPOSE
Display a list of available products.
DATA
Implement a backend REST API that provides product data. Each product should contain at least: id, name, price, shortDescription, thumbnailUrl.
FUNCTIONALITY
Fetch and display the product list from the backend. Display for each product: Product name, Price, Thumbnail image. Clicking a product should navigate to the Product Details Page. Implement robust server-side filtering, for example: Filter by product name, Filter by category. Implement sorting options, for example: Sort by price, Sort by name.
2. PRODUCT DETAILS PAGE
PURPOSE
Display detailed information for a selected product.
DATA
In addition to the fields above, each product should include: longDescription, category, reviews.
FUNCTIONALITY
Display: Product name, Price, Large thumbnail image, Short description, Long description, Category, List of product reviews. Also implement: Back to Products navigation and an Add to Cart button that updates the global shopping cart state.
3. SHOPPING CART PAGE
PURPOSE
Allow users to review their shopping cart and proceed to a mock checkout.
FUNCTIONALITY
Display all items currently in the cart. Allow users to: Change product quantities, Remove products. Display a dynamically updated total price.
Backend Requirements
TECHNOLOGY
Implement a RESTful API using your preferred backend framework, for example: Python + FastAPI, Python + Flask (or another backend framework).
API REQUIREMENTS
Provide endpoints for: Product listing, Single product details, Shopping cart operations.
IMPLEMENTATION
Store data in a simple mock database (JSON/file/in-memory is acceptable). Filtering and sorting must be implemented on the server side

CACHING
Integrate caching logic with TTL(Redis)

TESTING & QUALITY
Write backend  unit tests for at least one feature
Expectations
CODE QUALITY
The project should demonstrate: Clean architecture, Modular design, Logical separation of components, Clear naming conventions.
LOADING STATES
Implement meaningful loading states for asynchronous operations. Examples: Skeleton loaders, Loading indicators.
FRONTEND REQUIREMENTS
VUE
Vue 3, Composition API.
TYPESCRIPT
The entire project must be written in TypeScript. Define interfaces such as: ProductReview, CartItem.
ROUTING
Use Vue Router.
STATE MANAGEMENT
Use Pinia for global shopping cart state management.
STYLING
The application should have: Clean UI, Responsive layout (desktop + mobile). You may use: CSS, SCSS, CSS Modules. Preferred: Tailwind CSS.
COMPONENT LIBRARY
You may use any UI component library. Preferred: PrimeVue.
GIT
Initialize a Git repository. Use Git with meaningful commits throughout development.
ERROR HANDLING
Implement basic error handling, for example: Product does not exist (invalid product ID), Invalid application routes (404 page), API request failures. Graceful handling of network failures is encouraged.
TESTING & QUALITY
Write unit tests for at least one feature, for example: Filtering logic, Shopping cart store, Component behavior. Consider basic accessibility (A11y), including: Keyboard navigation, Accessible interactive elements.

DOCUMENTATION
Provide comprehensive project documentation, including:
Frontend: Instructions for setup, dependencies, and running the application.
Backend: API documentation, setup instructions, and endpoint descriptions.
Docker: Configuration files (Dockerfile, docker-compose.yml) and setup/run instructions.

Bonus (Extras)
Deploy the frontend using: GitHub Pages, Vercel, Netlify, or another hosting service. Improve error handling for unreliable network conditions. Dockerize the application using Docker Compose.
