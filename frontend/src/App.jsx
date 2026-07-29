import { HashRouter, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Home from './pages/Home'
import Products from './pages/Products'
import ProductDetail from './pages/ProductDetail'
import Ingredients from './pages/Ingredients'
import IngredientDetail from './pages/IngredientDetail'
import Compare from './pages/Compare'
import Chat from './pages/Chat'
import Roundtable from './pages/Roundtable'

export default function App() {
  return (
    <HashRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Home />} />
          <Route path="products" element={<Products />} />
          <Route path="products/:id" element={<ProductDetail />} />
          <Route path="ingredients" element={<Ingredients />} />
          <Route path="ingredients/:id" element={<IngredientDetail />} />
          <Route path="compare" element={<Compare />} />
          <Route path="chat" element={<Chat />} />
          <Route path="roundtable" element={<Roundtable />} />
          <Route path="*" element={<Home />} />
        </Route>
      </Routes>
    </HashRouter>
  )
}
