<script>
  export let items = [];
  
  // Default sample data if no items provided
  if (items.length === 0) {
    items = [
      {
        id: 1,
        title: 'Wireless Headphones',
        description: 'Premium noise-canceling wireless headphones with 30-hour battery life.',
        price: 199,
        icon: '📦'
      },
      {
        id: 2,
        title: 'Smart Watch',
        description: 'Advanced fitness tracking with heart rate monitor and GPS.',
        price: 299,
        icon: '⌚'
      },
      {
        id: 3,
        title: 'Phone Case',
        description: 'Protective silicone case with wireless charging compatibility.',
        price: 29,
        icon: '📱'
      }
    ];
  }
</script>

<div class="container">
  <div class="header">
    <h1>Products</h1>
    <p>Discover our collection</p>
  </div>
  
  <div class="card-tray">
    {#each items as item}
      <div class="card">
        <div class="card-image">
          <span class="placeholder">{item.icon}</span>
        </div>
        <div class="card-title">{item.title}</div>
        <div class="card-desc">{item.description}</div>
        <div class="card-footer">
          <span class="card-price">${item.price}</span>
          <button class="card-btn">Add to Cart</button>
        </div>
      </div>
    {/each}
  </div>
</div>

<style>
  .container {
    width: 100%;
    max-width: 1200px;
    margin: 0 auto;
    padding: 3rem;
  }
  
  .header {
    text-align: center;
    margin-bottom: 3rem;
  }
  
  .header h1 {
    font-size: 2.5rem;
    font-weight: 700;
    color: #2c2c2c;
    margin-bottom: 0.5rem;
    letter-spacing: -0.02em;
  }
  
  .header p {
    color: #666;
    font-size: 1rem;
    margin: 0;
  }
  
  .card-tray {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 2rem;
  }
  
  .card {
    background: #e8e8e8;
    border-radius: 24px;
    padding: 1.5rem;
    box-shadow: 
      8px 8px 16px #d1d1d1,
      -8px -8px 16px #ffffff;
    transition: all 0.3s ease;
    cursor: pointer;
  }
  
  .card:hover {
    transform: translateY(-4px);
    box-shadow: 
      12px 12px 24px #d1d1d1,
      -12px -12px 24px #ffffff;
  }
  
  .card-image {
    width: 100%;
    height: 180px;
    border-radius: 16px;
    margin-bottom: 1.25rem;
    box-shadow: 
      inset 4px 4px 8px #d1d1d1,
      inset -4px -4px 8px #ffffff;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #e8e8e8;
  }
  
  .card-image .placeholder {
    font-size: 3rem;
    opacity: 0.5;
  }
  
  .card-title {
    font-size: 1.25rem;
    font-weight: 600;
    color: #2c2c2c;
    margin-bottom: 0.5rem;
  }
  
  .card-desc {
    font-size: 0.875rem;
    color: #666;
    margin-bottom: 1rem;
    line-height: 1.5;
  }
  
  .card-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  
  .card-price {
    font-size: 1.5rem;
    font-weight: 700;
    color: #2c2c2c;
  }
  
  .card-btn {
    padding: 0.75rem 1.5rem;
    border: none;
    border-radius: 12px;
    background: #e8e8e8;
    color: #2c2c2c;
    font-weight: 600;
    font-size: 0.875rem;
    cursor: pointer;
    box-shadow: 
      4px 4px 8px #d1d1d1,
      -4px -4px 8px #ffffff;
    transition: all 0.2s ease;
  }
  
  .card-btn:hover {
    box-shadow: 
      6px 6px 12px #d1d1d1,
      -6px -6px 12px #ffffff;
  }
  
  .card-btn:active {
    box-shadow: 
      inset 4px 4px 8px #d1d1d1,
      inset -4px -4px 8px #ffffff;
  }
</style>
